"""/api/* usage, budget, and CLI-proxy routes for the BR-KG agent web service.

Carved out of ``agent/web_service.py``: the plain ``@app.route('/api/...')``
handlers for usage summary/records, budget status, and the CLI proxy. Registered
via ``register(app)`` (called by web_service each import; robust to per-test app
reimport). Cycle-free at module load; the couple of web_service helpers used
(``simple_chat_internal`` / ``logger``) are imported back lazily inside the
handlers.
"""

from __future__ import annotations

from flask import jsonify, request


def usage_summary():
    """
    Get LLM usage summary with cost breakdown.

    Query Parameters:
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        provider: Filter by provider (google, openai, etc.)
        bill_to: Filter by billing target (local_oauth, byok, managed)
        workspace_id: Filter by workspace ID
        hours: Last N hours (overrides start/end)

    Returns:
        JSON with usage aggregation by provider, model, and billing target
    """
    from brain_researcher.services.agent.web_service import logger

    try:
        from brain_researcher.services.agent.usage_aggregator import UsageTracker

        tracker = UsageTracker()

        # Get query parameters
        hours = request.args.get("hours", type=int)
        start_date = request.args.get("start")
        end_date = request.args.get("end")
        provider = request.args.get("provider")
        bill_to = request.args.get("bill_to")
        workspace_id = request.args.get("workspace_id")

        # Query usage
        if hours:
            summary = tracker.get_recent_usage(hours=hours)
            time_range = f"last_{hours}_hours"
        else:
            summary = tracker.get_usage_summary(
                start_date=start_date,
                end_date=end_date,
                provider=provider,
                bill_to=bill_to,
                workspace_id=workspace_id,
            )
            time_range = f"{start_date or 'all'}_{end_date or 'all'}"

        # Don't return full records in API (too verbose)
        num_records = len(summary.get("records", []))
        summary["records"] = (
            f"{num_records} records (use /api/usage/records for details)"
        )
        summary["time_range"] = time_range

        return jsonify(summary)

    except Exception as e:
        logger.error(f"Usage summary error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def usage_records():
    """
    Get detailed LLM usage records.

    Query Parameters:
        Same as /api/usage/summary
        limit: Max number of records to return (default: 100)

    Returns:
        JSON array of usage records
    """
    from brain_researcher.services.agent.web_service import logger

    try:
        from brain_researcher.services.agent.usage_aggregator import UsageTracker

        tracker = UsageTracker()

        # Get query parameters
        hours = request.args.get("hours", type=int)
        start_date = request.args.get("start")
        end_date = request.args.get("end")
        provider = request.args.get("provider")
        bill_to = request.args.get("bill_to")
        workspace_id = request.args.get("workspace_id")
        limit = request.args.get("limit", default=100, type=int)

        # Query usage
        if hours:
            summary = tracker.get_recent_usage(hours=hours)
        else:
            summary = tracker.get_usage_summary(
                start_date=start_date,
                end_date=end_date,
                provider=provider,
                bill_to=bill_to,
                workspace_id=workspace_id,
            )

        records = summary.get("records", [])

        # Apply limit
        if limit and len(records) > limit:
            records = records[:limit]

        return jsonify(
            {
                "records": records,
                "total_count": len(summary.get("records", [])),
                "returned_count": len(records),
            }
        )

    except Exception as e:
        logger.error(f"Usage records error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def budget_status():
    """
    Get current LLM budget status and limits.

    Note: Budget enforcement (Track 1) is not yet implemented.
    This endpoint returns a placeholder response.

    Returns:
        JSON with budget limits and spending (placeholder)
    """
    # Placeholder for Track 1 BudgetTracker integration
    return jsonify(
        {
            "status": "not_implemented",
            "message": "Budget enforcement (Track 1) is not yet implemented",
            "limits": {
                "daily_usd": None,
                "monthly_usd": None,
                "daily_tokens": None,
                "monthly_tokens": None,
            },
            "spent": {
                "daily_usd": 0.0,
                "monthly_usd": 0.0,
                "daily_tokens": 0,
                "monthly_tokens": 0,
            },
            "remaining": {
                "daily_usd": None,
                "monthly_usd": None,
                "daily_tokens": None,
                "monthly_tokens": None,
            },
        }
    )


def cli_proxy():
    """
    CLI proxy endpoint for @brainr/cli HTTP transport.
    Executes CLI commands and returns the output.
    """
    from brain_researcher.services.agent.web_service import (
        logger,
        simple_chat_internal,
    )

    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        argv = data.get("argv", [])
        env_override = data.get("env", {})

        # Parse the first argument as command
        if not argv:
            return jsonify({"error": "No command provided"}), 400

        command = argv[0] if argv else "help"

        # Route to appropriate handler based on command
        if command == "chat":
            # Extract prompt from args
            prompt = None
            for i, arg in enumerate(argv):
                if arg in ["-p", "--prompt"] and i + 1 < len(argv):
                    prompt = argv[i + 1]
                    break

            if not prompt:
                return jsonify({"error": "No prompt provided for chat"}), 400

            # Call the chat endpoint logic
            return simple_chat_internal(prompt, env_override)

        elif command == "ask":
            # Similar to chat but single-turn
            prompt = None
            for i, arg in enumerate(argv):
                if arg in ["-p", "--prompt"] and i + 1 < len(argv):
                    prompt = argv[i + 1]
                    break

            if not prompt:
                return jsonify({"error": "No prompt provided for ask"}), 400

            return simple_chat_internal(prompt, env_override)

        elif command == "version":
            return jsonify({"version": "0.1.0", "service": "brain-researcher"}), 200

        elif command == "help" or command == "--help":
            help_text = """Brain Researcher CLI - Available commands:
  chat      - Interactive chat with the assistant
  ask       - Single question mode
  act       - Execute tools based on query
  version   - Show version information
  help      - Show this help message
"""
            return help_text, 200, {"Content-Type": "text/plain"}

        else:
            return jsonify({"error": f"Unknown command: {command}"}), 400

    except Exception as e:
        logger.error(f"CLI proxy error: {e}")
        return jsonify({"error": str(e)}), 500


def register(app):
    """Register the /api/* usage/budget/cli routes on the Flask app (called each import)."""
    app.add_url_rule("/api/usage/summary", methods=["GET"], view_func=usage_summary)
    app.add_url_rule("/api/usage/records", methods=["GET"], view_func=usage_records)
    app.add_url_rule("/api/budget/status", methods=["GET"], view_func=budget_status)
    app.add_url_rule("/api/cli", methods=["POST"], view_func=cli_proxy)
