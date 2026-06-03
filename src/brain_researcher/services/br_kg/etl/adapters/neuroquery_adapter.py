from __future__ import annotations

from collections.abc import Iterable

from .base import EvidenceAdapter


class NeuroQueryAdapter(EvidenceAdapter):
    """Adapter returning NeuroQuery task-region association scores."""

    def __init__(self, *, data_path: str | None = None) -> None:
        super().__init__(
            data_path=data_path, default_source="neuroquery", default_score_key="score"
        )

    def fetch(
        self,
        *,
        task_ids: Iterable[str] | None = None,
        region_ids: Iterable[str] | None = None,
    ) -> list[dict]:
        return super().fetch(task_ids=task_ids, region_ids=region_ids)
