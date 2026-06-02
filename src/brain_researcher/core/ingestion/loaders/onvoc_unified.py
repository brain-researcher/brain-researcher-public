"""Unified loader for the OpenNeuro Vocabulary (ONVOC)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class OnvocUnifiedLoader:
    """Utility for reading ONVOC concepts and hierarchy artifacts."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir or "data/ontologies/onvoc")
        self._concepts_path = self.data_dir / "onvoc_concepts.json"
        self._relationships_path = self.data_dir / "onvoc_relationships.json"

    def _load_json(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required ONVOC artifact missing: {path}. Run scripts/tools/once/parse_onvoc_owl.py first."
            )
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def load_concepts(self) -> List[Dict[str, Any]]:
        """Return ONVOC concept payloads."""

        concepts = self._load_json(self._concepts_path)
        logger.debug(
            "Loaded %d ONVOC concepts from %s", len(concepts), self._concepts_path
        )
        return concepts

    def load_relationships(self) -> List[Dict[str, Any]]:
        """Return ONVOC hierarchical relationships."""

        relationships = self._load_json(self._relationships_path)
        logger.debug(
            "Loaded %d ONVOC relationships from %s",
            len(relationships),
            self._relationships_path,
        )
        return relationships
