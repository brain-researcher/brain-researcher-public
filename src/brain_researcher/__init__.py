"""Brain Researcher - Neuroimaging analysis platform."""

__version__ = "0.1.0"

# Avoid heavyweight side effects during package import. The runner helper can
# pull in the legacy tool registry, which drags large ML stacks into unrelated
# services such as BR-KG before the HTTP server binds.
#
# Keep the compatibility hook available as an explicit opt-in for CLI/debug
# sessions that truly need it.
try:  # pragma: no cover
    import os
    import importlib

    if os.getenv("BR_ENABLE_TOOL_RUNNER_IMPORT", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        importlib.import_module("brain_researcher.services.tools.runner")
except Exception:
    pass
