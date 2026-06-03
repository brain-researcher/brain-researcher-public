from __future__ import annotations

from typing import Iterable, List, Optional

from .base import EvidenceAdapter


class NiMAREAdapter(EvidenceAdapter):
    """Adapter returning NiMARE-derived task-region evidence."""

    def __init__(self, *, data_path: Optional[str] = None) -> None:
        super().__init__(data_path=data_path, default_source="nimare", default_score_key="probability")

    def fetch(self, *, task_ids: Optional[Iterable[str]] = None, region_ids: Optional[Iterable[str]] = None) -> List[dict]:
        return super().fetch(task_ids=task_ids, region_ids=region_ids)
