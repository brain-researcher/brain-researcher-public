from __future__ import annotations

from typing import Iterable, List, Optional

from .base import EvidenceAdapter


class AllenHBAAdapter(EvidenceAdapter):
    """Adapter providing Allen Human Brain Atlas gene expression summaries."""

    def __init__(self, *, data_path: Optional[str] = None) -> None:
        super().__init__(
            data_path=data_path,
            default_source="allen_hba",
            default_score_key="expression",
        )

    def fetch(
        self,
        *,
        region_ids: Optional[Iterable[str]] = None,
        gene_symbols: Optional[Iterable[str]] = None,
    ) -> List[dict]:
        region_set = frozenset(region_ids or [])
        gene_set = frozenset(gene_symbols or [])
        payload = []
        for record in self._load_payload():
            region_id = record.get("region_id")
            gene = record.get("gene_symbol")
            if region_set and region_id not in region_set:
                continue
            if gene_set and gene not in gene_set:
                continue
            payload.append(
                {
                    "region_id": region_id,
                    "gene_symbol": gene,
                    "expression": record.get("expression"),
                    "source": record.get("source", "allen_hba"),
                    "tissue_type": record.get("tissue_type"),
                }
            )
        return payload

    def __call__(self, **kwargs):
        return self.fetch(**kwargs)
