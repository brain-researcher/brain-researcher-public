#!/usr/bin/env python3
"""
Simple startup script for the Brain Researcher API Gateway.

This script provides an easy way to start the API Gateway with
default configuration or custom settings.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add the src root so `brain_researcher` remains importable when invoked directly.
src_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(src_root))

import uvicorn

from brain_researcher.legacy.api_gateway import create_gateway, get_info


def setup_logging(debug: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=level,
        format=format_string,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("gateway.log"),
        ],
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Brain Researcher API Gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start with default settings
  python start_gateway.py

  # Start with custom config
  python start_gateway.py --config config.yaml --port 8080

  # Start in debug mode
  python start_gateway.py --debug --reload

  # Show version info
  python start_gateway.py --version
        """,
    )

    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)"
    )

    parser.add_argument(
        "--port", type=int, default=8080, help="Port to bind to (default: 8080)"
    )

    parser.add_argument("--config", help="Configuration file path (YAML or JSON)")

    parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with verbose logging"
    )

    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )

    parser.add_argument(
        "--version", action="store_true", help="Show version information and exit"
    )

    parser.add_argument(
        "--workers", type=int, default=1, help="Number of worker processes (default: 1)"
    )

    args = parser.parse_args()

    # Show version info
    if args.version:
        info = get_info()
        print(f"{info['name']} v{info['version']}")
        print(f"Author: {info['author']}")
        print(f"Description: {info['description']}")
        print()
        print("Features:")
        for feature in info["features"]:
            print(f"  • {feature}")
        print()
        print("Supported Services:")
        for service in info["supported_services"]:
            print(f"  • {service}")
        return

    # Setup logging
    setup_logging(args.debug)
    logger = logging.getLogger(__name__)

    # Show startup banner
    info = get_info()
    print("=" * 60)
    print(f" {info['name']} v{info['version']}")
    print("=" * 60)
    print(f"Starting on {args.host}:{args.port}")
    if args.config:
        print(f"Config: {args.config}")
    if args.debug:
        print("Debug mode: ENABLED")
    if args.reload:
        print("Auto-reload: ENABLED")
    print("=" * 60)

    try:
        # Create gateway app
        logger.info("Initializing API Gateway...")
        app = create_gateway(args.config)
        logger.info("✓ Gateway initialized successfully")

        # Check environment variables
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            logger.warning("REDIS_URL not set, using default: redis://localhost:6379/0")

        jwt_secret = os.getenv("JWT_SECRET_KEY")
        if not jwt_secret:
            logger.warning(
                "JWT_SECRET_KEY not set, using auto-generated key (not recommended for production)"
            )

        # Start server
        logger.info(f"Starting server on {args.host}:{args.port}")

        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            debug=args.debug,
            reload=args.reload,
            workers=(
                args.workers if not args.reload else 1
            ),  # reload doesn't work with multiple workers
            access_log=args.debug,
            log_level="debug" if args.debug else "info",
        )

    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        print("\n👋 Goodbye!")

    except Exception as e:
        logger.error(f"Failed to start gateway: {e}")
        if args.debug:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
