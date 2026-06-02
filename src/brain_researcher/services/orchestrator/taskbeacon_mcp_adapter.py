"""Compatibility module alias for TaskBeacon MCP adapter helpers."""

from __future__ import annotations

import sys

from brain_researcher.services.tools import taskbeacon_mcp_adapter as _impl

sys.modules[__name__] = _impl
