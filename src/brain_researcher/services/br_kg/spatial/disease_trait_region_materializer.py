"""Materialize derived DiseaseTrait -> BrainRegion associations."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DERIVED_SOURCE = "disease_trait_region_materializer"
ASSOCIATED_WITH_REL = "ASSOCIATED_WITH"
DEFAULT_EVIDENCE_CAP = 25
REGION_LABELS = {"BrainRegion", "Region"}


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _coerce_text(value)
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(text)
    return tuple(out)


def _node_labels(db: Any, node_id: str) -> set[str]:
    node = None
    if hasattr(db, "get_node"):
        try:
            node = db.get_node(node_id)
        except Exception:  # pragma: no cover - defensive
            node = None
    if node is None and hasattr(db, "find_nodes"):
        try:
            matches = db.find_nodes(properties={"id": node_id})
        except Exception:  # pragma: no cover - defensive
            matches = []
        if matches:
            node = dict(matches[0][1])
    labels = node.get("labels", []) if isinstance(node, dict) else []
    return {str(label) for label in labels if _coerce_text(label)}


def _has_label(db: Any, node_id: str, label: str) -> bool:
    return label in _node_labels(db, node_id)


def _is_region_node(db: Any, node_id: str) -> bool:
    return bool(_node_labels(db, node_id) & REGION_LABELS)


def _node_name(db: Any, node_id: str) -> str | None:
    node = None
    if hasattr(db, "get_node"):
        try:
            node = db.get_node(node_id)
        except Exception:  # pragma: no cover - defensive
            node = None
    if node is None and hasattr(db, "find_nodes"):
        try:
            matches = db.find_nodes(properties={"id": node_id})
        except Exception:  # pragma: no cover - defensive
            matches = []
        if matches:
            node = dict(matches[0][1])
    if not isinstance(node, dict):
        return None
    return _coerce_text(node.get("name") or node.get("label") or node_id)


@dataclass
class DiseaseTraitRegionEvidence:
    disease_trait_id: str
    region_id: str
    region_name: str | None = None
    supporting_publication_ids: list[str] = field(default_factory=list)
    supporting_study_ids: list[str] = field(default_factory=list)
    supporting_coordinate_ids: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)

    def add_publication(self, publication_id: str) -> None:
        self.supporting_publication_ids.append(publication_id)
        self.evidence_paths.append(f"publication:{publication_id}")

    def add_study(self, study_id: str) -> None:
        self.supporting_study_ids.append(study_id)
        self.evidence_paths.append(f"study:{study_id}")

    def add_coordinate(self, coordinate_id: str) -> None:
        self.supporting_coordinate_ids.append(coordinate_id)
        self.evidence_paths.append(f"coordinate:{coordinate_id}")

    def to_properties(
        self, *, max_evidence_ids: int = DEFAULT_EVIDENCE_CAP
    ) -> dict[str, Any]:
        publication_ids = _ordered_unique(self.supporting_publication_ids)
        study_ids = _ordered_unique(self.supporting_study_ids)
        coordinate_ids = _ordered_unique(self.supporting_coordinate_ids)
        evidence_ids = _ordered_unique(
            list(publication_ids) + list(study_ids) + list(coordinate_ids)
        )
        if max_evidence_ids >= 0:
            publication_ids = publication_ids[:max_evidence_ids]
            study_ids = study_ids[:max_evidence_ids]
            coordinate_ids = coordinate_ids[:max_evidence_ids]
            evidence_ids = evidence_ids[:max_evidence_ids]

        support_scale = (
            len(publication_ids) * 0.35
            + len(study_ids) * 0.2
            + len(coordinate_ids) * 0.15
        )
        confidence = min(1.0, 0.35 + support_scale)

        properties: dict[str, Any] = {
            "source": DERIVED_SOURCE,
            "derived": True,
            "method": "graph_evidence_aggregation",
            "derivation": _ordered_unique(
                [
                    "aligned_publication_mentions_region" if publication_ids else "",
                    "study_coordinate_region" if coordinate_ids else "",
                ]
            ),
            "evidence_mode": "derived",
            "supporting_publication_count": len(publication_ids),
            "supporting_study_count": len(study_ids),
            "supporting_coordinate_count": len(coordinate_ids),
            "supporting_publication_ids": list(publication_ids),
            "supporting_study_ids": list(study_ids),
            "supporting_coordinate_ids": list(coordinate_ids),
            "evidence_ids": list(evidence_ids),
            "confidence": confidence,
        }
        if self.region_name:
            properties["region_name"] = self.region_name
        return properties


@dataclass
class DiseaseTraitRegionMaterializationSummary:
    disease_traits_seen: int = 0
    region_pairs_collected: int = 0
    edges_created: int = 0
    edges_updated: int = 0
    edges_skipped_existing: int = 0
    edges_skipped_missing_region: int = 0
    edges_skipped_missing_disease_trait: int = 0
    publication_paths: int = 0
    coordinate_paths: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _find_relationship_starts(
    db: Any,
    *,
    end_node: str,
    rel_type: str,
) -> list[str]:
    try:
        rels = db.find_relationships(end_node=end_node, rel_type=rel_type)
    except Exception:  # pragma: no cover - defensive
        return []
    return [str(start) for start, _end, _data in rels]


def _find_relationship_ends(
    db: Any,
    *,
    start_node: str,
    rel_type: str,
) -> list[str]:
    try:
        rels = db.find_relationships(start_node=start_node, rel_type=rel_type)
    except Exception:  # pragma: no cover - defensive
        return []
    return [str(end) for _start, end, _data in rels]


def _collect_from_publication_path(
    db: Any,
    *,
    disease_trait_id: str,
    study_id: str,
    evidence_by_region: dict[str, DiseaseTraitRegionEvidence],
) -> int:
    publication_ids = _find_relationship_starts(
        db,
        end_node=study_id,
        rel_type="ALIGNS_WITH",
    )
    count = 0
    for publication_id in publication_ids:
        if not _has_label(db, publication_id, "Publication"):
            continue
        region_ids = _find_relationship_ends(
            db,
            start_node=publication_id,
            rel_type="MENTIONS_REGION",
        )
        for region_id in region_ids:
            if not _is_region_node(db, region_id):
                continue
            evidence = evidence_by_region.setdefault(
                region_id,
                DiseaseTraitRegionEvidence(
                    disease_trait_id=disease_trait_id,
                    region_id=region_id,
                    region_name=_node_name(db, region_id),
                ),
            )
            evidence.add_publication(publication_id)
            evidence.add_study(study_id)
            count += 1
    return count


def _collect_from_coordinate_path(
    db: Any,
    *,
    disease_trait_id: str,
    study_id: str,
    evidence_by_region: dict[str, DiseaseTraitRegionEvidence],
) -> int:
    coordinate_ids = _find_relationship_ends(
        db,
        start_node=study_id,
        rel_type="HAS_COORDINATE",
    )
    count = 0
    for coordinate_id in coordinate_ids:
        region_ids = _find_relationship_ends(
            db,
            start_node=coordinate_id,
            rel_type="LOCATED_IN",
        )
        for region_id in region_ids:
            if not _is_region_node(db, region_id):
                continue
            evidence = evidence_by_region.setdefault(
                region_id,
                DiseaseTraitRegionEvidence(
                    disease_trait_id=disease_trait_id,
                    region_id=region_id,
                    region_name=_node_name(db, region_id),
                ),
            )
            evidence.add_coordinate(coordinate_id)
            evidence.add_study(study_id)
            count += 1
    return count


def collect_disease_trait_region_evidence(
    db: Any,
    *,
    disease_trait_ids: Iterable[str] | None = None,
    max_evidence_ids: int = DEFAULT_EVIDENCE_CAP,
) -> dict[str, dict[str, DiseaseTraitRegionEvidence]]:
    """Collect DiseaseTrait -> BrainRegion evidence from existing graph paths."""
    evidence: dict[str, dict[str, DiseaseTraitRegionEvidence]] = {}

    disease_traits: list[tuple[str, dict[str, Any]]] = []
    if disease_trait_ids is not None:
        seen_ids: set[str] = set()
        for disease_trait_id in disease_trait_ids:
            key = _coerce_text(disease_trait_id)
            if not key or key in seen_ids:
                continue
            seen_ids.add(key)
            props = {}
            if hasattr(db, "get_node"):
                try:
                    node = db.get_node(key)
                except Exception:  # pragma: no cover - defensive
                    node = None
                if isinstance(node, dict):
                    props = dict(node)
            disease_traits.append((key, props))
    else:
        try:
            disease_traits = list(db.find_nodes(labels="DiseaseTrait"))
        except Exception:  # pragma: no cover - defensive
            return evidence

    for disease_trait_id, _disease_trait_props in disease_traits:
        disease_trait_id = str(disease_trait_id)
        disease_trait_map: dict[str, DiseaseTraitRegionEvidence] = {}
        evidence[disease_trait_id] = disease_trait_map

        if not _has_label(db, disease_trait_id, "DiseaseTrait"):
            continue

        source_ids = _find_relationship_starts(
            db,
            end_node=disease_trait_id,
            rel_type="STUDIES",
        )
        study_ids = [
            source_id for source_id in source_ids if _has_label(db, source_id, "Study")
        ]
        publication_ids = [
            source_id
            for source_id in source_ids
            if _has_label(db, source_id, "Publication")
        ]

        for publication_id in publication_ids:
            region_ids = _find_relationship_ends(
                db,
                start_node=publication_id,
                rel_type="MENTIONS_REGION",
            )
            for region_id in region_ids:
                if not _is_region_node(db, region_id):
                    continue
                evidence_row = disease_trait_map.setdefault(
                    region_id,
                    DiseaseTraitRegionEvidence(
                        disease_trait_id=disease_trait_id,
                        region_id=region_id,
                        region_name=_node_name(db, region_id),
                    ),
                )
                evidence_row.add_publication(publication_id)

        for study_id in study_ids:
            if not _has_label(db, study_id, "Study"):
                continue
            _collect_from_publication_path(
                db,
                disease_trait_id=disease_trait_id,
                study_id=study_id,
                evidence_by_region=disease_trait_map,
            )
            _collect_from_coordinate_path(
                db,
                disease_trait_id=disease_trait_id,
                study_id=study_id,
                evidence_by_region=disease_trait_map,
            )

        if disease_trait_map:
            for region_id, evidence_row in disease_trait_map.items():
                evidence_row.supporting_publication_ids = list(
                    _ordered_unique(evidence_row.supporting_publication_ids)[
                        :max_evidence_ids
                    ]
                )
                evidence_row.supporting_study_ids = list(
                    _ordered_unique(evidence_row.supporting_study_ids)[
                        :max_evidence_ids
                    ]
                )
                evidence_row.supporting_coordinate_ids = list(
                    _ordered_unique(evidence_row.supporting_coordinate_ids)[
                        :max_evidence_ids
                    ]
                )
                evidence_row.evidence_paths = list(
                    _ordered_unique(evidence_row.evidence_paths)[:max_evidence_ids]
                )

    return evidence


def _upsert_associated_with_edge(
    db: Any,
    *,
    disease_trait_id: str,
    region_id: str,
    properties: dict[str, Any],
) -> str:
    existing = []
    try:
        existing = db.find_relationships(
            start_node=disease_trait_id,
            end_node=region_id,
            rel_type=ASSOCIATED_WITH_REL,
        )
    except Exception:  # pragma: no cover - defensive
        existing = []

    if existing:
        try:
            update_relationship = db.update_relationship
        except Exception:  # pragma: no cover - defensive
            update_relationship = None
        if callable(update_relationship):
            updated = update_relationship(
                disease_trait_id,
                region_id,
                ASSOCIATED_WITH_REL,
                properties,
            )
            return "updated" if updated else "skipped"
        return "skipped"

    created = db.create_relationship(
        disease_trait_id,
        region_id,
        ASSOCIATED_WITH_REL,
        properties,
    )
    return "created" if created else "error"


def materialize_disease_trait_region_associations(
    db: Any,
    *,
    disease_trait_ids: Iterable[str] | None = None,
    max_evidence_ids: int = DEFAULT_EVIDENCE_CAP,
    dry_run: bool = False,
) -> DiseaseTraitRegionMaterializationSummary:
    """Materialize derived DiseaseTrait -> BrainRegion ASSOCIATED_WITH edges."""
    summary = DiseaseTraitRegionMaterializationSummary()
    evidence = collect_disease_trait_region_evidence(
        db,
        disease_trait_ids=disease_trait_ids,
        max_evidence_ids=max_evidence_ids,
    )
    summary.disease_traits_seen = len(evidence)

    for disease_trait_id, region_map in evidence.items():
        if not _has_label(db, disease_trait_id, "DiseaseTrait"):
            summary.edges_skipped_missing_disease_trait += len(region_map)
            continue

        for region_id, evidence_row in region_map.items():
            if not _is_region_node(db, region_id):
                summary.edges_skipped_missing_region += 1
                continue

            summary.region_pairs_collected += 1
            properties = evidence_row.to_properties(max_evidence_ids=max_evidence_ids)
            if dry_run:
                summary.edges_created += 1
                continue

            if properties.get("supporting_publication_count"):
                summary.publication_paths += 1
            if properties.get("supporting_coordinate_count"):
                summary.coordinate_paths += 1

            outcome = _upsert_associated_with_edge(
                db,
                disease_trait_id=disease_trait_id,
                region_id=region_id,
                properties=properties,
            )
            if outcome == "created":
                summary.edges_created += 1
            elif outcome == "updated":
                summary.edges_updated += 1
            elif outcome == "skipped":
                summary.edges_skipped_existing += 1
            else:
                summary.errors += 1

    return summary


__all__ = [
    "ASSOCIATED_WITH_REL",
    "DEFAULT_EVIDENCE_CAP",
    "DERIVED_SOURCE",
    "DiseaseTraitRegionEvidence",
    "DiseaseTraitRegionMaterializationSummary",
    "collect_disease_trait_region_evidence",
    "materialize_disease_trait_region_associations",
]
