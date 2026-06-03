"""Metrics collection for Istio migration workflows (test/local stub)."""

from __future__ import annotations

import time
from typing import Any, Dict, List


class MigrationMetricsCollector:
    """Collect basic metrics for migrations."""

    def __init__(self):
        self._timers: Dict[str, float] = {}
        self._operation_counts: Dict[str, Dict[str, int]] = {}
        self._rollback_events: List[Dict[str, Any]] = []

    def start_migration_timer(self, migration_id: str) -> None:
        self._timers[migration_id] = time.time()

    def end_migration_timer(self, migration_id: str) -> float:
        start = self._timers.pop(migration_id, time.time())
        duration = time.time() - start
        return duration

    def record_operation_result(self, migration_id: str, success: bool) -> None:
        counts = self._operation_counts.setdefault(migration_id, {"success": 0, "failure": 0})
        if success:
            counts["success"] += 1
        else:
            counts["failure"] += 1

    def calculate_error_rate(self, migration_id: str) -> float:
        counts = self._operation_counts.get(migration_id, {"success": 0, "failure": 0})
        total = counts["success"] + counts["failure"]
        if total == 0:
            return 0.0
        return counts["failure"] / total

    def record_rollback_event(self, rollback_event: Dict[str, Any]) -> None:
        self._rollback_events.append(dict(rollback_event))

    def get_rollback_statistics(self) -> Dict[str, Any]:
        total = len(self._rollback_events)
        reasons = [event.get("reason") for event in self._rollback_events if event.get("reason")]
        avg_time = 0.0
        if total:
            avg_time = sum(event.get("rollback_duration", 0) for event in self._rollback_events) / total
        return {
            "total_rollbacks": total,
            "rollback_reasons": reasons,
            "average_rollback_time": avg_time,
        }
