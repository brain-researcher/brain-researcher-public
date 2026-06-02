"""
Shared in-memory job state for the orchestrator and job-management routers.
"""

from __future__ import annotations

from datetime import datetime

from brain_researcher.services.shared.job_update_bus import job_updates as job_updates

from .models import Job, Message, Thread

# Core job/book-keeping stores shared between /run and /api/jobs
jobs_db: dict[str, Job] = {}
threads_db: dict[str, Thread] = {}
messages_db: dict[str, list[Message]] = {}
service_start_time = datetime.utcnow()
