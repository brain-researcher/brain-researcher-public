"""Job lifecycle contracts shared across services.

Relocated from ``services/orchestrator/job_store.py`` so lower layers (agent,
tools, mcp) can type and construct job records without importing the
orchestrator — this removes a set of ``*-> orchestrator`` back-edges for these
pure contracts. ``JobRecord`` is an alias of the core contract
``JobRecordV1``; ``JobState`` is a standalone string enum. ``job_store``
re-exports both for backward compatibility.
"""

from __future__ import annotations

from enum import Enum

from brain_researcher.core.contracts.job import JobRecordV1

JobRecord = JobRecordV1


class JobState(str, Enum):
    """Job state enumeration matching existing JobStatus."""

    PENDING = "pending"
    QUEUED = "queued"
    CLAIMED = "claimed"  # New: worker has claimed but not started
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    CANCELLING = "cancelling"  # New: cancellation requested but not finalized
    SKIPPED = "skipped"  # New: DAG node skipped due to upstream failure
    PAUSED = "paused"
    RETRYING = "retrying"
