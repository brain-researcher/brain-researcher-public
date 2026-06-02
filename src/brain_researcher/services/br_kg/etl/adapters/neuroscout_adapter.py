from __future__ import annotations

from typing import Iterable, List, Optional

from .base import EvidenceAdapter


class NeuroscoutAdapter(EvidenceAdapter):
    """Adapter retrieving Neuroscout feature annotations for contrasts."""

    def __init__(self, *, data_path: Optional[str] = None) -> None:
        super().__init__(
            data_path=data_path, default_source="neuroscout", default_score_key="value"
        )

    def fetch(
        self,
        *,
        contrast_ids: Optional[Iterable[str]] = None,
        feature_names: Optional[Iterable[str]] = None,
    ) -> List[dict]:
        feature_set = frozenset(feature_names or [])
        contrast_set = frozenset(contrast_ids or [])
        records = []
        for record in self._load_payload():
            contrast_id = record.get("contrast_id")
            feature = record.get("feature")
            if contrast_set and contrast_id not in contrast_set:
                continue
            if feature_set and feature not in feature_set:
                continue
            result = {
                "contrast_id": contrast_id,
                "feature": feature,
                "value": record.get("value"),
                "unit": record.get("unit"),
                "source": record.get("source", "neuroscout"),
            }
            records.append(result)
        return records

    def __call__(self, **kwargs):
        return self.fetch(**kwargs)
