"""Concurrent migration runner for Istio migrations (test/local stub)."""

from __future__ import annotations

import asyncio
from typing import Any


class ConcurrentMigrator:
    """Execute migration tasks with a concurrency cap."""

    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self.max_concurrent_reached_count = 0
        self._inflight = 0
        self._lock = asyncio.Lock()

    def create_migration_task(
        self, service_name: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        return {"service": service_name, "config": dict(config)}

    async def _run_task(
        self, task: dict[str, Any], semaphore: asyncio.Semaphore
    ) -> dict[str, Any]:
        async with semaphore:
            async with self._lock:
                self._inflight += 1
                if self._inflight >= self.max_concurrent:
                    self.max_concurrent_reached_count += 1
            await asyncio.sleep(0.01)
            async with self._lock:
                self._inflight -= 1
            return {"service": task["service"], "completed": True}

    async def execute_migrations(
        self, tasks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(self.max_concurrent)
        coros = [self._run_task(task, semaphore) for task in tasks]
        return list(await asyncio.gather(*coros))
