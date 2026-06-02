"""Shared in-process queues for job update SSE streams."""

from __future__ import annotations

import asyncio
from typing import Any

job_updates: dict[str, asyncio.Queue[Any]] = {}
