"""
Configuration resolver for agent service.

Provides startup-time resolution of service endpoints and configuration.
"""

import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# Cached configuration
_config = {}


def resolve_neurokg_url() -> str:
    """
    Resolve BR-KG API URL with precedence:
    1. Explicit environment variable (NEUROKG_API_URL or NEUROKG_URL)
    2. Service discovery (Docker/K8s DNS) – prefer port 5000
    3. Localhost fallback – prefer port 5000
    """
    cache_key = "NEUROKG_API_URL"

    # Check cache first
    if cache_key in _config:
        return _config[cache_key]

    # 1) Explicit env (support both *_API_URL and *_URL aliases)
    env_url = os.getenv("NEUROKG_API_URL") or os.getenv("NEUROKG_URL")
    if env_url:
        logger.info(f"Using BR-KG URL from environment: {env_url}")
        _config[cache_key] = env_url
        return env_url

    # 2) Service discovery inside Docker/K8s (prefer 5000)
    for url in ["http://neurokg:5000"]:
        try:
            response = requests.get(f"{url}/health", timeout=1)
            if response.ok:
                logger.info(f"Found BR-KG via service discovery at: {url}")
                _config[cache_key] = url
                return url
        except Exception:
            continue

    # 3) Localhost fallback (for bare-metal dev)
    for url in ["http://localhost:5000"]:
        try:
            response = requests.get(f"{url}/health", timeout=1)
            if response.ok:
                logger.info(f"Found BR-KG on localhost at: {url}")
                _config[cache_key] = url
                return url
        except Exception:
            continue

    raise RuntimeError(
        "Unable to resolve BR-KG endpoint. "
        "Set NEUROKG_API_URL (or NEUROKG_URL) or ensure the service is reachable on port 5000."
    )


def is_demo_mode() -> bool:
    """Check if running in demo mode (allows synthetic data)."""
    return os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")


def get_config() -> dict:
    """Get all resolved configuration."""
    if not _config:
        # Resolve all config at startup
        try:
            _config["NEUROKG_API_URL"] = resolve_neurokg_url()
        except Exception as e:
            logger.warning(f"Failed to resolve BR-KG URL: {e}")
            _config["NEUROKG_API_URL"] = None
        
        _config["DEMO_MODE"] = is_demo_mode()
        _config["MAX_TOOL_TIMEOUT_MS"] = int(os.getenv("MAX_TOOL_TIMEOUT_MS", "30000"))
        _config["DEFAULT_BUDGET_MS"] = int(os.getenv("DEFAULT_BUDGET_MS", "90000"))
        
        logger.info(f"Agent configuration: {_config}")
    
    return _config
