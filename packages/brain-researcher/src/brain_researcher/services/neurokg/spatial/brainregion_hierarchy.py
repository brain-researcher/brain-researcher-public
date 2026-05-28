"""Materialize canonical BrainRegion hierarchy edges for BR-KG."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

PARENT_COLUMN_CANDIDATES = (
    "parent",
    "superregion",
    "lobe",
    "macroregion",
    "network_parent",
)

NAME_COLUMN_CANDIDATES = ("name", "region", "parcel", "label", "node", "structure")
LABEL_COLUMN_CANDIDATES = ("label", "longname", "fullname", "region_label")

YEO17_CHILD_TO_FAMILY = {
    "VisCent": "Visual",
    "VisPeri": "Visual",
    "SomMotA": "Somatomotor",
    "SomMotB": "Somatomotor",
    "DorsAttnA": "Dorsal Attention",
    "DorsAttnB": "Dorsal Attention",
    "SalVentAttnA": "Salience/Ventral Attention",
    "SalVentAttnB": "Salience/Ventral Attention",
    "LimbicA": "Limbic",
    "LimbicB": "Limbic",
    "ContA": "Control",
    "ContB": "Control",
    "ContC": "Control",
    "DefaultA": "Default",
    "DefaultB": "Default",
    "DefaultC": "Default",
    "TempPar": "Temporal-Parietal",
}

YEO17_INDEX_TO_NAME = {
    1: "VisCent",
    2: "VisPeri",
    3: "SomMotA",
    4: "SomMotB",
    5: "DorsAttnA",
    6: "DorsAttnB",
    7: "SalVentAttnA",
    8: "SalVentAttnB",
    9: "LimbicA",
    10: "LimbicB",
    11: "ContA",
    12: "ContB",
    13: "ContC",
    14: "DefaultA",
    15: "DefaultB",
    16: "DefaultC",
    17: "TempPar",
}


@dataclass
class HierarchySummary:
    scope: str
    parent_nodes_created: int = 0
    part_of_created: int = 0
    part_of_skipped: int = 0
    rows_skipped: int = 0
    unresolved_children: int = 0
    unresolved_parents: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def slugify(value: str) -> str:
    """Convert free text to a stable identifier slug."""
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "_", value)
    value = re.sub(r"[\s\-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def detect_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    """Best-effort case-insensitive column detection."""
    normalized: dict[str, str] = {}
    for col in columns:
        key = re.sub(r"[^a-z0-9]", "", col.lower())
        normalized[key] = col

    for candidate in candidates:
        candidate_key = re.sub(r"[^a-z0-9]", "", candidate.lower())
        if candidate_key in normalized:
            return normalized[candidate_key]
    return None


def string_or_none(value: object) -> str | None:
    """Normalize dataframe / graph values into a usable string."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _candidate_keys(*values: object) -> set[str]:
    keys: set[str] = set()
    for value in values:
        text = string_or_none(value)
        if not text:
            continue
        keys.add(text.lower())
        keys.add(slugify(text))
    return keys


def _node_id(node_id: str, data: dict[str, Any]) -> str:
    return str(data.get("id") or node_id)


def _parse_int(value: object) -> int | None:
    text = string_or_none(value)
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _node_matches_atlas(node_id: str, data: dict[str, Any], atlas_slug: str) -> bool:
    atlas = string_or_none(data.get("atlas"))
    atlas_node_slug = string_or_none(data.get("atlas_slug"))
    node_ident = _node_id(node_id, data).lower()
    atlas_candidates = {
        atlas_slug,
        atlas_slug.replace("_", ""),
    }
    if atlas:
        atlas_candidates.add(slugify(atlas))
    if atlas_node_slug:
        atlas_candidates.add(slugify(atlas_node_slug))

    if any(candidate and candidate in node_ident for candidate in atlas_candidates):
        return True
    if atlas and slugify(atlas) == atlas_slug:
        return True
    if atlas_node_slug and slugify(atlas_node_slug) == atlas_slug:
        return True
    return False


def _collect_brainregions(
    db: Any,
    *,
    atlas_slug: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    nodes = db.find_nodes(labels="BrainRegion")
    if atlas_slug is None:
        return [(_node_id(node_id, data), data) for node_id, data in nodes]
    return [
        (_node_id(node_id, data), data)
        for node_id, data in nodes
        if _node_matches_atlas(node_id, data, atlas_slug)
    ]


def _build_lookup(
    nodes: Iterable[tuple[str, dict[str, Any]]],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for node_id, data in nodes:
        for key in _candidate_keys(
            node_id,
            data.get("region_id"),
            data.get("name"),
            data.get("label"),
        ):
            lookup.setdefault(key, node_id)
    return lookup


def _relationship_exists(db: Any, start_node: str, end_node: str) -> bool:
    existing = db.find_relationships(
        start_node=start_node,
        end_node=end_node,
        rel_type="PART_OF",
    )
    return bool(existing)


def _ensure_parent_node(
    db: Any,
    parent_id: str,
    properties: dict[str, Any],
    *,
    dry_run: bool,
    pending_parent_ids: set[str],
) -> bool:
    if parent_id in pending_parent_ids:
        return False
    existing = db.find_nodes(labels="BrainRegion", properties={"id": parent_id})
    if existing:
        return False
    pending_parent_ids.add(parent_id)
    if dry_run:
        return True
    db.create_node("BrainRegion", properties, node_id=parent_id)
    return True


def _ensure_part_of_edge(
    db: Any,
    child_id: str,
    parent_id: str,
    properties: dict[str, Any],
    *,
    dry_run: bool,
    pending_edges: set[tuple[str, str]],
) -> bool:
    if child_id == parent_id:
        return False
    edge_key = (child_id, parent_id)
    if edge_key in pending_edges:
        return False
    if _relationship_exists(db, child_id, parent_id):
        return False
    pending_edges.add(edge_key)
    if not dry_run:
        db.create_relationship(child_id, parent_id, "PART_OF", properties)
    return True


def materialize_explicit_part_of_from_dataframe(
    db: Any,
    *,
    atlas: str,
    df: pd.DataFrame,
    dry_run: bool = False,
) -> HierarchySummary:
    """Create BrainRegion hierarchy edges from explicit atlas metadata."""
    summary = HierarchySummary(scope=f"explicit:{atlas}")
    atlas_slug = slugify(atlas)
    nodes = _collect_brainregions(db, atlas_slug=atlas_slug)
    if not nodes:
        logger.info("No BrainRegion nodes found for atlas %s; skipping explicit pass", atlas)
        summary.rows_skipped = int(len(df.index))
        return summary

    name_col = detect_column(df.columns, NAME_COLUMN_CANDIDATES)
    parent_col = detect_column(df.columns, PARENT_COLUMN_CANDIDATES)
    label_col = detect_column(df.columns, LABEL_COLUMN_CANDIDATES)
    if not name_col or not parent_col:
        summary.rows_skipped = int(len(df.index))
        return summary

    child_lookup = _build_lookup(nodes)
    atlas_name = string_or_none(nodes[0][1].get("atlas")) or atlas
    pending_parent_ids: set[str] = set()
    pending_edges: set[tuple[str, str]] = set()

    for _, row in df.iterrows():
        child_name = string_or_none(row[name_col])
        parent_name = string_or_none(row[parent_col])
        if not child_name or not parent_name:
            summary.rows_skipped += 1
            continue

        child_id = None
        for key in _candidate_keys(child_name, row[label_col] if label_col else None):
            child_id = child_lookup.get(key)
            if child_id:
                break

        if not child_id:
            summary.unresolved_children += 1
            summary.rows_skipped += 1
            continue

        parent_id = None
        for key in _candidate_keys(parent_name):
            parent_id = child_lookup.get(key)
            if parent_id:
                break

        hierarchy_type = "network" if slugify(parent_col) == "network_parent" else "anatomical"

        if not parent_id:
            parent_id = f"atlas:{atlas_slug}:parent:{slugify(parent_name)}"
            created = _ensure_parent_node(
                db,
                parent_id,
                {
                    "id": parent_id,
                    "region_id": parent_id,
                    "name": parent_name,
                    "atlas": atlas_name,
                    "atlas_slug": atlas_slug,
                    "source": "brainregion_hierarchy_materializer",
                    "hierarchy_level": "parent",
                    "derived_from": "atlas_metadata",
                },
                dry_run=dry_run,
                pending_parent_ids=pending_parent_ids,
            )
            if created:
                summary.parent_nodes_created += 1
            for key in _candidate_keys(parent_name, parent_id):
                child_lookup[key] = parent_id

        if child_id == parent_id:
            summary.rows_skipped += 1
            continue

        created_edge = _ensure_part_of_edge(
            db,
            child_id,
            parent_id,
            {
                "source": "brainregion_hierarchy_materializer",
                "derivation": "atlas_metadata",
                "atlas": atlas_slug,
                "hierarchy_type": hierarchy_type,
            },
            dry_run=dry_run,
            pending_edges=pending_edges,
        )
        if created_edge:
            summary.part_of_created += 1
        else:
            summary.part_of_skipped += 1

    return summary


def _infer_yeo17_family(node_id: str, data: dict[str, Any]) -> str | None:
    name = string_or_none(data.get("name"))
    if name and name in YEO17_CHILD_TO_FAMILY:
        return YEO17_CHILD_TO_FAMILY[name]

    label_index = _parse_int(data.get("label_index"))
    if label_index is None:
        match = re.search(r"yeo17:(\d{2})", _node_id(node_id, data), flags=re.IGNORECASE)
        if match:
            label_index = int(match.group(1))
    if label_index is None:
        return None

    yeo_name = YEO17_INDEX_TO_NAME.get(label_index)
    if yeo_name is None:
        return None
    return YEO17_CHILD_TO_FAMILY.get(yeo_name)


def materialize_yeo17_family_part_of(
    db: Any,
    *,
    dry_run: bool = False,
) -> HierarchySummary:
    """Materialize network-family PART_OF edges for Yeo17 BrainRegion nodes."""
    summary = HierarchySummary(scope="fallback:yeo17")
    nodes = _collect_brainregions(db, atlas_slug="yeo17")
    if not nodes:
        return summary

    pending_parent_ids: set[str] = set()
    pending_edges: set[tuple[str, str]] = set()
    for node_id, data in nodes:
        if node_id.startswith("yeo17:parent:"):
            continue

        family = _infer_yeo17_family(node_id, data)
        if not family:
            summary.rows_skipped += 1
            continue

        parent_id = f"yeo17:parent:{slugify(family)}"
        created_parent = _ensure_parent_node(
            db,
            parent_id,
            {
                "id": parent_id,
                "region_id": parent_id,
                "name": family,
                "atlas": "Yeo17",
                "atlas_slug": "yeo17",
                "source": "brainregion_hierarchy_materializer",
                "hierarchy_level": "network_parent",
                "derived_from": "yeo17_name_family_map",
            },
            dry_run=dry_run,
            pending_parent_ids=pending_parent_ids,
        )
        if created_parent:
            summary.parent_nodes_created += 1

        created_edge = _ensure_part_of_edge(
            db,
            node_id,
            parent_id,
            {
                "source": "brainregion_hierarchy_materializer",
                "derivation": "yeo17_family_fallback",
                "atlas": "yeo17",
                "hierarchy_type": "network",
            },
            dry_run=dry_run,
            pending_edges=pending_edges,
        )
        if created_edge:
            summary.part_of_created += 1
        else:
            summary.part_of_skipped += 1

    return summary


def materialize_schaefer_network_part_of(
    db: Any,
    *,
    dry_run: bool = False,
) -> HierarchySummary:
    """Materialize atlas-local Schaefer network parents from node metadata."""
    summary = HierarchySummary(scope="fallback:schaefer")
    nodes = _collect_brainregions(db)
    schaefer_nodes = [
        (node_id, data)
        for node_id, data in nodes
        if "schaefer" in (
            string_or_none(data.get("atlas_slug"))
            or string_or_none(data.get("atlas"))
            or node_id
        ).lower()
    ]
    if not schaefer_nodes:
        return summary

    pending_parent_ids: set[str] = set()
    pending_edges: set[tuple[str, str]] = set()
    for node_id, data in schaefer_nodes:
        if string_or_none(data.get("hierarchy_level")) == "network_parent":
            continue

        network = string_or_none(data.get("network"))
        if not network:
            summary.rows_skipped += 1
            continue

        atlas_slug = string_or_none(data.get("atlas_slug"))
        if not atlas_slug:
            atlas_slug = slugify(string_or_none(data.get("atlas")) or "schaefer")

        atlas_name = string_or_none(data.get("atlas")) or atlas_slug
        parent_id = f"atlas:{atlas_slug}:network:{slugify(network)}"
        created_parent = _ensure_parent_node(
            db,
            parent_id,
            {
                "id": parent_id,
                "region_id": parent_id,
                "name": network,
                "atlas": atlas_name,
                "atlas_slug": atlas_slug,
                "yeo_network_set": data.get("yeo_network_set"),
                "source": "brainregion_hierarchy_materializer",
                "hierarchy_level": "network_parent",
                "derived_from": "atlas_network_field",
            },
            dry_run=dry_run,
            pending_parent_ids=pending_parent_ids,
        )
        if created_parent:
            summary.parent_nodes_created += 1

        created_edge = _ensure_part_of_edge(
            db,
            node_id,
            parent_id,
            {
                "source": "brainregion_hierarchy_materializer",
                "derivation": "atlas_network_field",
                "atlas": atlas_slug,
                "hierarchy_type": "network",
            },
            dry_run=dry_run,
            pending_edges=pending_edges,
        )
        if created_edge:
            summary.part_of_created += 1
        else:
            summary.part_of_skipped += 1

    return summary
