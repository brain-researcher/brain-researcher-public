"""
Unified loader for Neuromaps parcellations and atlas metadata.

This module wraps the procedural utilities in
``brain_researcher.core.ingestion.loaders.neuromaps_parcellations`` and
exposes a class-based API that fits the ingestion framework used by
``brain_researcher.services.neurokg.etl.load_all``.  The loader discovers atlas
definitions staged on disk, builds BrainRegion node payloads via the shared
helpers, and writes them into BR-KG while tracking ingestion statistics.
"""

from __future__ import annotations

import io
import logging
import os
import re
from collections import defaultdict
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neuromaps.datasets import annotations

from brain_researcher.core.ingestion.graph_factory import GraphDatabaseProtocol
from brain_researcher.core.ingestion.loaders import (
    neuromaps_parcellations as neuromaps_runtime,
)
from brain_researcher.core.ingestion.neuromaps_paths import preferred_neuromaps_root

logger = logging.getLogger(__name__)


class NeuromapsUnifiedLoader:
    """High-level interface for ingesting Neuromaps parcellations into BR-KG."""

    def __init__(self, base_path: Optional[str | Path] = None) -> None:
        """
        Initialize the loader.

        Args:
            base_path: Root directory containing Neuromaps resources. Defaults to
                the shared atlas home when available, otherwise the legacy raw
                repo cache.
        """
        default_base = preferred_neuromaps_root()
        if base_path is None:
            self.base_path = default_base.expanduser().resolve()
        else:
            self.base_path = Path(base_path).expanduser().resolve()

    @staticmethod
    def _normalize_identifiers(
        values: Optional[Sequence[str] | str],
    ) -> Optional[List[str]]:
        """Normalize include/exclude arguments into a list of atlas identifiers."""
        if values is None:
            return None
        if isinstance(values, str):
            if "," in values:
                return [item.strip() for item in values.split(",") if item.strip()]
            stripped = values.strip()
            return [stripped] if stripped else None
        normalized: List[str] = []
        for value in values:
            text = str(value).strip()
            if text:
                normalized.append(text)
        return normalized or None

    def discover_atlases(
        self,
        include: Optional[Sequence[str] | str] = None,
        exclude: Optional[Sequence[str] | str] = None,
    ) -> List[neuromaps_runtime.AtlasFile]:
        """
        Discover Neuromaps atlas definition files.

        Args:
            include: Optional iterable or comma-separated string of atlas filters.
            exclude: Optional iterable or comma-separated string of atlas filters.

        Returns:
            List of :class:`AtlasFile` descriptors to process.
        """
        include_list = self._normalize_identifiers(include)
        exclude_list = self._normalize_identifiers(exclude)
        return neuromaps_runtime.discover_atlas_files(
            self.base_path,
            include=include_list,
            exclude=exclude_list,
        )

    def load_parcellations(
        self,
        *,
        db: Optional[GraphDatabaseProtocol],
        include: Optional[Sequence[str] | str] = None,
        exclude: Optional[Sequence[str] | str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Load Neuromaps parcellations into the provided BR-KG database connection.

        Args:
            db: Active graph database connection used for inserts.
            include: Optional iterable or comma-separated string limiting atlases.
            exclude: Optional iterable or comma-separated string of atlases to skip.
            dry_run: When ``True``, compute statistics without writing to the DB.

        Returns:
            Dictionary with ingestion statistics mirroring ``load_all.load_neuromaps``.
        """
        if db is None:
            raise ValueError(
                "NeuromapsUnifiedLoader.load_parcellations requires a database handle."
            )

        try:
            atlas_files = self.discover_atlases(include=include, exclude=exclude)
        except FileNotFoundError as exc:
            logger.error("Neuromaps base path not found: %s", exc)
            raise

        result: Dict[str, Any] = {
            "base_path": str(self.base_path),
            "atlases_discovered": len(atlas_files),
            "atlases_processed": 0,
            "atlases_failed": 0,
            "nodes_created": 0,
            "nodes_skipped": 0,
            "part_of_created": 0,
            "part_of_skipped": 0,
            "dry_run": dry_run,
        }

        if not atlas_files:
            logger.warning(
                "No Neuromaps atlas files discovered under %s", self.base_path
            )
            return result

        logger.info("Discovered %d Neuromaps atlas file(s)", len(atlas_files))

        for atlas_file in atlas_files:
            logger.info(
                "Processing Neuromaps atlas: %s (%s)", atlas_file.atlas, atlas_file.path
            )
            try:
                df = neuromaps_runtime.read_table(atlas_file.path)
            except ValueError as exc:
                logger.warning("Skipping atlas %s: %s", atlas_file.atlas, exc)
                result["atlases_failed"] += 1
                continue
            except Exception as exc:  # pragma: no cover - unexpected read issues
                logger.error(
                    "Failed to read atlas %s: %s", atlas_file.atlas, exc, exc_info=True
                )
                result["atlases_failed"] += 1
                continue

            try:
                (
                    nodes_created,
                    nodes_skipped,
                    node_lookup,
                    column_info,
                ) = neuromaps_runtime.insert_brain_regions(
                    db=db,
                    atlas_file=atlas_file,
                    df=df,
                    dry_run=dry_run,
                )
                name_col = column_info.get("name_col")
                parent_col = column_info.get("parent_col")
                part_of_created, part_of_skipped = (
                    neuromaps_runtime.insert_part_of_relationships(
                        db=db,
                        atlas_file=atlas_file,
                        df=df,
                        node_id_lookup=node_lookup,
                        parent_col=parent_col,
                        name_col=name_col,
                        dry_run=dry_run,
                    )
                )
            except ValueError as exc:
                logger.warning(
                    "Skipping atlas %s during ingestion: %s", atlas_file.atlas, exc
                )
                result["atlases_failed"] += 1
                continue
            except Exception as exc:  # pragma: no cover - ingestion issues
                logger.error(
                    "Failed to ingest atlas %s: %s",
                    atlas_file.atlas,
                    exc,
                    exc_info=True,
                )
                result["atlases_failed"] += 1
                continue

            result["atlases_processed"] += 1
            result["nodes_created"] += nodes_created
            result["nodes_skipped"] += nodes_skipped
            result["part_of_created"] += part_of_created
            result["part_of_skipped"] += part_of_skipped

        if dry_run:
            logger.info(
                "Neuromaps loader executed in dry-run mode; no database writes were made."
            )

        if result["atlases_processed"] == 0 and result["atlases_failed"] > 0:
            logger.warning(
                "All discovered Neuromaps atlases failed to ingest; inspect the logs for details.",
            )

        return result
        return result

    def load_annotation_metadata(
        self,
        *,
        db: Optional[GraphDatabaseProtocol],
        include_restricted: Optional[bool] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Materialize Neuromaps annotation metadata as BrainAnnotation nodes."""

        if db is None:
            raise ValueError(
                "NeuromapsUnifiedLoader.load_annotation_metadata requires a database handle."
            )

        include_restricted = bool(include_restricted)
        entries = annotations.get_dataset_info("annotations", include_restricted)
        grouped: Dict[Tuple[str, str, str, Optional[str]], Dict[str, Any]] = (
            defaultdict(
                lambda: {
                    "files": set(),
                    "hemispheres": set(),
                    "formats": set(),
                    "tags": set(),
                    "urls": set(),
                    "title": None,
                    "resolution": None,
                    "restricted": include_restricted,
                }
            )
        )

        for entry in entries:
            source = entry.get("source")
            desc = entry.get("desc")
            space = entry.get("space")
            density = entry.get("den") or entry.get("res")
            if not (source and desc and space):
                continue
            key = (source, desc, space, density)
            group = grouped[key]

            rel_path = Path(entry.get("rel_path") or "")
            fname = entry.get("fname")
            if fname:
                full_path = (
                    self.base_path / "annotations" / rel_path / fname
                ).resolve()
                group["files"].add(str(full_path))

            hemi = entry.get("hemi")
            if hemi:
                group["hemispheres"].add(hemi)

            fmt = entry.get("format")
            if fmt:
                group["formats"].add(fmt)

            tags = entry.get("tags") or []
            group["tags"].update(tags)

            url = entry.get("url")
            if url:
                group["urls"].add(url)

            title = entry.get("title")
            if title and not group["title"]:
                group["title"] = title

            if entry.get("res"):
                group["resolution"] = entry["res"]

        annotations_created = 0
        annotations_skipped = 0
        annotations_updated = 0
        annotations_failed = 0

        for key, payload in grouped.items():
            try:
                props = self._build_annotation_properties(key, payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Skipping Neuromaps annotation %s due to error: %s", key, exc
                )
                annotations_failed += 1
                continue

            node_id = props["id"]
            existing = db.find_nodes("BrainAnnotation", {"id": node_id})
            if existing:
                if dry_run:
                    annotations_skipped += 1
                    continue
                try:
                    db.create_node("BrainAnnotation", props, node_id=node_id)
                    annotations_updated += 1
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "Failed to update BrainAnnotation %s: %s", node_id, exc
                    )
                    annotations_failed += 1
                continue

            if dry_run:
                annotations_created += 1
                continue

            try:
                db.create_node("BrainAnnotation", props)
                annotations_created += 1
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to create BrainAnnotation %s: %s", node_id, exc)
                annotations_failed += 1

        if annotations_created or annotations_skipped:
            logger.info(
                "Processed Neuromaps annotations: %d created, %d updated, %d skipped",
                annotations_created,
                annotations_updated,
                annotations_skipped,
            )

        return {
            "annotations_discovered": len(grouped),
            "annotations_created": annotations_created,
            "annotations_updated": annotations_updated,
            "annotations_skipped": annotations_skipped,
            "annotations_failed": annotations_failed,
        }

    def load(
        self,
        db: Optional[GraphDatabaseProtocol],
        *,
        include: Optional[Sequence[str] | str] = None,
        exclude: Optional[Sequence[str] | str] = None,
        dry_run: bool = False,
        include_restricted: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Alias for :meth:`load_parcellations` for API symmetry with other loaders."""
        result = self.load_parcellations(
            db=db,
            include=include,
            exclude=exclude,
            dry_run=dry_run,
        )

        if include_restricted is None:
            include_restricted = bool(os.getenv("NEUROMAPS_OSF_TOKEN"))

        annotation_stats = self.load_annotation_metadata(
            db=db,
            include_restricted=include_restricted,
            dry_run=dry_run,
        )
        result.update(annotation_stats)
        return result

    @staticmethod
    def _annotation_id(
        source: str, desc: str, space: str, density: Optional[str]
    ) -> str:
        slug = neuromaps_runtime.slugify(
            ":".join(part for part in (source, desc, space, density or "na"))
        )
        return f"neuromaps:annotation:{slug}"

    def _capture_annotation_summary(
        self,
        key: Tuple[str, str, str, Optional[str]],
    ) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            annotations.describe_annotations([key])
        return buf.getvalue().strip()

    @staticmethod
    def _parse_annotation_summary(summary: str) -> Dict[str, Any]:
        if not summary:
            return {}

        metadata: Dict[str, Any] = {}

        sample_match = re.search(r"N\s+([0-9]+(?:\.[0-9]+)?)", summary)
        if sample_match:
            try:
                metadata["sample_size"] = float(sample_match.group(1))
            except ValueError:
                pass

        age_match = re.search(r"Age\s+([0-9\.]+)\s*(?:\+/-|±)\s*([0-9\.]+)", summary)
        if age_match:
            try:
                metadata["age_mean"] = float(age_match.group(1))
                metadata["age_sd"] = float(age_match.group(2))
            except ValueError:
                pass

        primary_refs: List[str] = []
        secondary_refs: List[str] = []
        current = None
        for line in summary.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("Primary references:"):
                current = "primary"
                continue
            if stripped.startswith("Secondary references:"):
                current = "secondary"
                continue
            if current == "primary":
                primary_refs.append(stripped)
            elif current == "secondary":
                secondary_refs.append(stripped)

        if primary_refs:
            metadata["primary_references"] = primary_refs
        if secondary_refs:
            metadata["secondary_references"] = [
                ref for ref in secondary_refs if ref not in ("()", "")
            ]

        metadata["summary"] = summary
        return metadata

    def _build_annotation_properties(
        self,
        key: Tuple[str, str, str, Optional[str]],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        source, desc, space, density = key
        summary_text = self._capture_annotation_summary(key)
        summary_info = self._parse_annotation_summary(summary_text)

        properties: Dict[str, Any] = {
            "id": self._annotation_id(source, desc, space, density),
            "source": "neuromaps",
            "dataset": source,
            "description": desc,
            "space": space,
            "density": density,
            "formats": sorted(payload["formats"]) if payload["formats"] else None,
            "hemispheres": (
                sorted(payload["hemispheres"]) if payload["hemispheres"] else None
            ),
            "files": sorted(payload["files"]),
            "tags": sorted(payload["tags"]) if payload["tags"] else None,
            "title": payload["title"],
            "urls": sorted(payload["urls"]) if payload["urls"] else None,
            "restricted": bool(payload.get("restricted")),
            "summary": summary_info.get("summary", summary_text),
        }

        if payload.get("resolution"):
            properties.setdefault("resolution", payload["resolution"])

        for numeric_key in ("sample_size", "age_mean", "age_sd"):
            if summary_info.get(numeric_key) is not None:
                properties[numeric_key] = summary_info[numeric_key]

        if summary_info.get("primary_references"):
            properties["primary_references"] = summary_info["primary_references"]
        if summary_info.get("secondary_references"):
            properties["secondary_references"] = summary_info["secondary_references"]

        return {
            key: value
            for key, value in properties.items()
            if value not in (None, [], {})
        }


__all__ = ["NeuromapsUnifiedLoader"]
