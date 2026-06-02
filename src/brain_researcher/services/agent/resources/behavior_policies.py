"""Lightweight loader for behavior outlier policies.

Implementation relocated to ``services/shared/toolsagent_behavior_policies`` so
that the lower ``services/tools`` layer can depend on it without importing from
``services/agent``. This module re-exports the public API for existing callers.
"""

from __future__ import annotations

from brain_researcher.services.shared.toolsagent_behavior_policies import (
    DEFAULT_POLICY_DIR,
    DEFAULT_POLICY_PATH,
    load_behavior_policies,
)

__all__ = ["load_behavior_policies", "DEFAULT_POLICY_PATH", "DEFAULT_POLICY_DIR"]
