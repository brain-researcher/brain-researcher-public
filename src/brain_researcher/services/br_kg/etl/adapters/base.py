"""Utilities for simple evidence adapters."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class EvidenceAdapter:
    """Base adapter that loads task-region evidence scores from JSON."""

    def __init__(
        self,
        *,
        data_path: str | None = None,
        default_source: str = "",
        default_score_key: str = "score",
    ) -> None:
        self.data_path = Path(data_path) if data_path else None
        self.default_source = default_source
        self.default_score_key = default_score_key

    def _load_payload(self) -> list[dict[str, Any]]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise FileNotFoundError(
                f"Evidence adapter path not found: {self.data_path}"
            )
        text = self.data_path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            # allow {"records": [...]}
            data = data.get("records", [])
        if not isinstance(data, list):
            raise ValueError("Evidence adapter payload must be a JSON array")
        return data

    def fetch(
        self,
        *,
        task_ids: Iterable[str] | None = None,
        region_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        task_set = frozenset(task_ids or [])
        region_set = frozenset(region_ids or [])
        payload = []
        for record in self._load_payload():
            task_id = record.get("task_id")
            region_id = record.get("region_id")
            if task_set and task_id not in task_set:
                continue
            if region_set and region_id not in region_set:
                continue
            result = {
                "task_id": task_id,
                "region_id": region_id,
                self.default_score_key: record.get(
                    self.default_score_key, record.get("score")
                ),
                "source": record.get("source", self.default_source),
            }
            # include optional metadata
            for key in ("confidence", "method", "evidence_json"):
                if key in record:
                    result[key] = record[key]
            payload.append(result)
        return payload

    def __call__(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.fetch(**kwargs)
