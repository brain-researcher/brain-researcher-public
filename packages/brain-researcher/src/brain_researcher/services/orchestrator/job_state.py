"""
Shared in-memory job state for the orchestrator and job-management routers.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from typing import Dict, List

from .models import Job, Message, Thread

# Core job/book-keeping stores shared between /run and /api/jobs
jobs_db: Dict[str, Job] = {}
job_updates: Dict[str, asyncio.Queue] = {}
threads_db: Dict[str, Thread] = {}
messages_db: Dict[str, List[Message]] = {}
service_start_time = datetime.utcnow()
