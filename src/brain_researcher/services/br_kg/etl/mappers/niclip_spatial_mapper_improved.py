"""
Compatibility wrapper over the real NiCLIP coordinate mapper.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Sequence

from brain_researcher.services.br_kg.niclip.coordinate_mapper import (
    NiCLIPCoordinateMapper,
)

logger = logging.getLogger(__name__)


class ImprovedNiCLIPSpatialMapper:
    """
    Backward-compatible mapper interface that delegates to real NiCLIP backends.
    """

    def __init__(self, niclip_path: Optional[Path | str] = None):
        self._backend = NiCLIPCoordinateMapper(niclip_path=niclip_path)
        self.niclip_path = self._backend.niclip_path
        self.task_priors = dict(getattr(self._backend, "task_priors", {}))
        self.concept_to_process = dict(getattr(self._backend, "concept_to_process", {}))
        # Preserve attribute used by legacy verification script.
        self.concept_map = self.concept_to_process
        self.concept_priors = {}
        self.prior_percentiles = {}
        self._loaded = bool(self._backend._loaded)

    def coordinate_to_concepts(
        self,
        coordinates: Sequence[Sequence[float]],
        radius: float = 10.0,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        if not self._loaded:
            return [
                {
                    "coordinate": tuple(coord),
                    "error": "Mapper not loaded",
                    "concepts": [],
                }
                for coord in coordinates
            ]
        payload = self._backend.map_with_metadata(
            coordinates, radius_mm=radius, top_k=top_k, allow_full=True
        )
        return payload["mappings"]

    def map_with_metadata(
        self,
        coordinates: Sequence[Sequence[float]],
        radius: float = 10.0,
        top_k: int = 5,
    ) -> dict[str, Any]:
        if not self._loaded:
            return {
                "mappings": [
                    {
                        "coordinate": tuple(coord),
                        "error": "Mapper not loaded",
                        "concepts": [],
                    }
                    for coord in coordinates
                ],
                "backend": "unavailable",
                "backend_counts": {"full": 0, "embedding_only": 0},
                "errors": ["mapper not loaded"],
                "niclip_data_path": str(self.niclip_path),
                "niclip_model_path": None,
            }
        return self._backend.map_with_metadata(
            coordinates, radius_mm=radius, top_k=top_k, allow_full=True
        )

    def get_task_brain_alignment(self, task_name: str) -> Optional[float]:
        return self._backend.get_task_brain_alignment(task_name)

    def get_concept_process(self, concept: str) -> Optional[str]:
        return self._backend.get_concept_process(concept)


_MAPPER_INSTANCE: Optional[ImprovedNiCLIPSpatialMapper] = None
_MAPPER_PATH: Optional[str] = None


def get_improved_mapper(
    niclip_path: Optional[Path | str] = None, *, force_reload: bool = False
) -> Optional[ImprovedNiCLIPSpatialMapper]:
    """Get or create improved spatial mapper instance."""
    global _MAPPER_INSTANCE, _MAPPER_PATH
    try:
        requested_path = str(Path(niclip_path).resolve()) if niclip_path else None
        if (
            force_reload
            or _MAPPER_INSTANCE is None
            or (requested_path is not None and requested_path != _MAPPER_PATH)
        ):
            _MAPPER_INSTANCE = ImprovedNiCLIPSpatialMapper(niclip_path=niclip_path)
            _MAPPER_PATH = requested_path
        return _MAPPER_INSTANCE
    except Exception as e:
        logger.error(f"Failed to create improved mapper: {e}")
        return None
