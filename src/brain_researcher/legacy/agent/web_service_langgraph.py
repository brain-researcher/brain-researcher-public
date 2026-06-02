#!/usr/bin/env python3
"""Legacy LangGraph compatibility entrypoint for the Agent service."""

import logging
import os

from brain_researcher.services.agent import runtime_bootstrap  # noqa: F401
from brain_researcher.services.agent.web_service import app, print_exposed_tools

logger = logging.getLogger(__name__)
logger.info("web_service_langgraph shim loaded - redirecting to main web_service.py")


def main() -> None:
    port = int(os.getenv("AGENT_PORT", 8000))
    debug = os.getenv("FLASK_ENV", "production") == "development"

    logger.info(f"Starting agent service on port {port} (via shim)")
    print_exposed_tools()
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    main()
