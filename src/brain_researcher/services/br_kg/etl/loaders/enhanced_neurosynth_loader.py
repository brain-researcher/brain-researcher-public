#!/usr/bin/env python3
"""Neurosynth loader backed by the pinned, locally verified source bundle."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from brain_researcher.core.datasets.neurosynth_source import (
    COORDINATES_FILENAME,
    DEFAULT_SOURCE_DIR,
    METADATA_FILENAME,
    VOCABULARY_FILENAME,
    verify_source_bundle,
)

logger = logging.getLogger(__name__)


class EnhancedNeurosynthLoader:
    """Load real Neurosynth coordinates, metadata, and labels fail-closed.

    ``cache_dir`` remains accepted for caller compatibility, but unversioned
    pickle caches are intentionally not read or written: they cannot establish
    that their contents came from the pinned public source bundle.
    """

    def __init__(self, data_dir: str | Path | None = None, cache_dir=None):
        self.data_dir = (
            Path(data_dir).expanduser().resolve()
            if data_dir is not None
            else DEFAULT_SOURCE_DIR
        )
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        self.coordinates_file = self.data_dir / COORDINATES_FILENAME
        self.metadata_file = self.data_dir / METADATA_FILENAME
        self.vocabulary_file = self.data_dir / VOCABULARY_FILENAME

        self.coordinates: pd.DataFrame | None = None
        self.metadata: pd.DataFrame | None = None
        self.labels: list[str] | None = None
        self.source_manifest: dict[str, Any] | None = None

    def load_data(self, use_cache: bool = True, force_reload: bool = False) -> dict:
        """Load the verified bundle; missing, stale, or corrupt input raises.

        ``use_cache`` controls only the in-memory values held by this instance.
        There is no automatic network fetch and no synthetic fallback.
        """
        self.source_manifest = verify_source_bundle(self.data_dir)
        if (
            use_cache
            and not force_reload
            and self.coordinates is not None
            and self.metadata is not None
            and self.labels is not None
        ):
            return self._result()

        try:
            coordinates = pd.read_csv(
                self.coordinates_file, sep="\t", compression="gzip"
            )
            metadata = pd.read_csv(self.metadata_file, sep="\t", compression="gzip")
            labels = [
                line.strip()
                for line in self.vocabulary_file.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            ]
        except Exception as exc:
            raise RuntimeError(
                f"failed to parse verified Neurosynth source bundle {self.data_dir}: {exc}"
            ) from exc

        if coordinates.empty:
            raise ValueError("verified Neurosynth coordinates table is empty")
        if metadata.empty:
            raise ValueError("verified Neurosynth metadata table is empty")
        if not labels:
            raise ValueError("verified Neurosynth vocabulary is empty")

        self.coordinates = coordinates
        self.metadata = metadata
        self.labels = labels
        logger.info(
            "Loaded verified Neurosynth bundle: %d coordinates, %d studies, %d terms",
            len(coordinates),
            len(metadata),
            len(labels),
        )
        return self._result()

    def _result(self) -> dict:
        return {
            "coordinates": self.coordinates,
            "metadata": self.metadata,
            "labels": self.labels,
            "source_manifest": self.source_manifest,
        }

    def get_studies_by_label(self, label):
        """Return metadata rows whose text contains ``label``."""
        if self.metadata is None:
            self.load_data()

        studies = []
        assert self.metadata is not None
        search_columns = [
            col
            for col in self.metadata.columns
            if "title" in col.lower() or "abstract" in col.lower()
        ]
        for col in search_columns:
            if self.metadata[col].dtype == "object":
                matches = self.metadata[
                    self.metadata[col].str.contains(
                        label.replace("_", " "), case=False, na=False
                    )
                ]
                studies.extend(row.to_dict() for _, row in matches.iterrows())

        logger.info("Found %d studies related to %r", len(studies), label)
        return studies

    def get_coordinates_by_study(self, study_id):
        """Return coordinates for one study identifier."""
        if self.coordinates is None:
            self.load_data()

        assert self.coordinates is not None
        if "id" in self.coordinates.columns:
            return self.coordinates[self.coordinates["id"] == study_id]
        return pd.DataFrame()

    def get_coordinates_by_label(self, label, max_studies=None):
        """Return coordinates for metadata rows matching ``label``."""
        studies = self.get_studies_by_label(label)
        if max_studies is not None:
            studies = studies[:max_studies]

        all_coordinates = []
        for study in studies:
            if "id" not in study:
                continue
            study_coords = self.get_coordinates_by_study(study["id"])
            if study_coords.empty:
                continue
            study_coords = study_coords.copy()
            for key, value in study.items():
                if key not in study_coords.columns:
                    study_coords[key] = value
            all_coordinates.append(study_coords)

        if all_coordinates:
            return pd.concat(all_coordinates, ignore_index=True)
        return pd.DataFrame()

    def get_all_labels(self):
        """Return the verified Neurosynth vocabulary."""
        if self.labels is None:
            self.load_data()
        return self.labels or []
