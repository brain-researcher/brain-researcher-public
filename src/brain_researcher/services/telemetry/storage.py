"""Persistence helpers for telemetry events."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional

from brain_researcher.config.paths import get_data_root

from .models import TelemetryEvent, _is_test_env

logger = logging.getLogger(__name__)


class TelemetryEventStore:
    """Durable storage for telemetry events using newline-delimited JSON."""

    def __init__(
        self,
        base_dir: Optional[os.PathLike[str] | str] = None,
        *,
        retention_days: Optional[int] = None,
    ) -> None:
        configured_dir = base_dir or os.getenv("TELEMETRY_DATA_DIR")
        data_root = (
            Path(configured_dir).expanduser()
            if configured_dir
            else get_data_root() / "telemetry"
        )
        self.base_path = data_root.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.events_file = self.base_path / "events.ndjson"
        self.retention_days = retention_days
        self._write_locks: dict[int, asyncio.Lock] = {}
        self._last_prune: Optional[datetime] = None

    def load_recent_events(
        self,
        max_age_days: Optional[int] = None,
        limit: Optional[int] = 5000,
    ) -> List[TelemetryEvent]:
        """Load recent events from disk (best-effort)."""
        if not self.events_file.exists():
            return []

        cutoff: Optional[datetime] = None
        if max_age_days:
            cutoff = datetime.utcnow() - timedelta(days=max_age_days)

        events: List[TelemetryEvent] = []
        try:
            with self.events_file.open("r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        event = TelemetryEvent(**payload)
                    except Exception:
                        logger.warning(
                            "Skipping malformed telemetry event line", exc_info=True
                        )
                        continue
                    if cutoff and event.timestamp < cutoff:
                        continue
                    events.append(event)
        except FileNotFoundError:
            return []

        if limit and len(events) > limit:
            events = events[-limit:]
        return events

    async def append_events(self, events: Iterable[TelemetryEvent]) -> None:
        """Persist a batch of telemetry events."""
        batch = list(events)
        if not batch:
            return

        lines = (
            "\n".join(json.dumps(evt.model_dump(mode="json")) for evt in batch) + "\n"
        )
        async with self._get_write_lock():
            if _is_test_env():
                # Avoid executor deadlocks in test harnesses.
                self._append_text(lines)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._append_text, lines)
        await self._maybe_prune()

    def append_events_sync(self, events: Iterable[TelemetryEvent]) -> None:
        """Synchronous persistence helper for test harnesses."""
        batch = list(events)
        if not batch:
            return
        lines = (
            "\n".join(json.dumps(evt.model_dump(mode="json")) for evt in batch) + "\n"
        )
        self._append_text(lines)
        self._maybe_prune_sync()

    def _get_write_lock(self) -> asyncio.Lock:
        """Return a loop-local write lock to avoid cross-loop deadlocks."""
        loop = asyncio.get_running_loop()
        key = id(loop)
        lock = self._write_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._write_locks[key] = lock
        return lock

    def _append_text(self, payload: str) -> None:
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        with self.events_file.open("a", encoding="utf-8") as fp:
            fp.write(payload)

    async def _maybe_prune(self) -> None:
        if not self.retention_days:
            return
        now = datetime.utcnow()
        if self._last_prune and (now - self._last_prune) < timedelta(hours=1):
            return
        self._last_prune = now
        if _is_test_env():
            self._prune_file()
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._prune_file)

    def _maybe_prune_sync(self) -> None:
        if not self.retention_days:
            return
        now = datetime.utcnow()
        if self._last_prune and (now - self._last_prune) < timedelta(hours=1):
            return
        self._last_prune = now
        self._prune_file()

    def _prune_file(self) -> None:
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days or 0)
        if cutoff <= datetime.min:
            return
        if not self.events_file.exists():
            return
        temp_path = self.events_file.with_suffix(".tmp")
        kept = 0
        with (
            self.events_file.open("r", encoding="utf-8") as src,
            temp_path.open("w", encoding="utf-8") as dst,
        ):
            for line in src:
                try:
                    payload = json.loads(line)
                    raw_ts = payload.get("timestamp")
                    if not raw_ts:
                        continue
                    timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                except Exception:
                    continue
                if timestamp < cutoff:
                    continue
                dst.write(json.dumps(payload) + "\n")
                kept += 1
        temp_path.replace(self.events_file)
        logger.debug("TelemetryEventStore pruned file, kept %s events", kept)


__all__ = ["TelemetryEventStore"]
