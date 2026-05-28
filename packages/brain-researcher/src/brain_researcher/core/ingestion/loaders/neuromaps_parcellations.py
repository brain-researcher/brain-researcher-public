"""
Reusable Neuromaps parcellation loading utilities.

This module discovers atlas definition files (CSV/TSV/JSON) exported from the
`neuromaps` dataset repository and converts them into `BrainRegion` nodes with
optional hierarchical `PART_OF` relationships. CLI wrappers should import these
helpers instead of carrying their own loading logic.

Expected directory layout (default: /app/data/atlases/neuromaps when available):

    neuromaps/
        schaefer2018_400p_7networks.tsv
        yeo17_networks.tsv
        aal116.csv
        ...

Each file should contain parcel metadata. The loader is column-name agnostic and
will search for common headers (e.g., "name", "label", "hemisphere", "network",
"parent", "x", "y", "z"). Unsupported columns are stored as metadata.

Example usage:

    python scripts/neurokg/load_neuromaps_parcellations.py \\
        --base-path /app/data/atlases/neuromaps \\
        --atlas schaefer2018_400p_7networks yeo17_networks

    python scripts/neurokg/load_neuromaps_parcellations.py \\
        --dry-run  # report without writing to the database
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol, Tuple

import nibabel as nib
import numpy as np
import pandas as pd
from nibabel.cifti2.cifti2_axes import LabelAxis

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data classes and helpers
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AtlasFile:
    """Descriptor for an input atlas file."""

    path: Path
    atlas: str


class NeuromapsGraphDBProtocol(Protocol):
    """Graph methods required by Neuromaps parcellation ingestion."""

    def find_nodes(
        self,
        labels: str | Iterable[str] | None = None,
        properties: Dict[str, object] | None = None,
    ) -> list: ...

    def create_node(
        self,
        labels: str | Iterable[str],
        properties: Dict[str, object] | None = None,
        node_id: str | None = None,
    ) -> object: ...

    def find_relationships(
        self,
        start_node: str | None = None,
        end_node: str | None = None,
        rel_type: str | None = None,
    ) -> list: ...

    def create_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: Dict[str, object] | None = None,
    ) -> object: ...


TABLE_SUFFIXES = {".tsv", ".txt", ".csv", ".json"}
LABEL_FILE_SUFFIXES = (".label.gii", ".dlabel.nii")
BACKGROUND_LABELS = {
    "",
    "unknown",
    "medialwall",
    "medial_wall",
    "??",
    "???",
    "background",
}


def slugify(value: str) -> str:
    """Convert a string to a filesystem/database friendly slug."""
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "_", value)
    value = re.sub(r"[\s\-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def detect_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    """
    Find a column name that matches one of the candidate identifiers.

    All comparisons are case-insensitive and ignore non-alphanumeric characters.
    """
    normalized = {}
    for col in columns:
        key = re.sub(r"[^a-z0-9]", "", col.lower())
        normalized[key] = col

    for candidate in candidates:
        candidate_key = re.sub(r"[^a-z0-9]", "", candidate.lower())
        if candidate_key in normalized:
            return normalized[candidate_key]
    return None


def _string_or_none(value: object, *, lowercase: bool = False) -> Optional[str]:
    """
    Normalize a cell value into a trimmed string or return None when empty/NaN.
    """
    if pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None
    if text.lower() == "nan":
        return None

    return text.lower() if lowercase else text


def _read_gifti_label_table(path: Path) -> pd.DataFrame:
    """Extract label metadata from a GIFTI label file."""

    img = nib.load(str(path))
    label_table = getattr(img, "labeltable", None)
    if label_table is None or not label_table.labels:
        raise ValueError(f"GIFTI label file {path} does not contain a label table")

    counts: Dict[int, int] = {}
    if img.darrays:
        data = np.asarray(img.darrays[0].data)
        unique, freq = np.unique(data, return_counts=True)
        counts = {int(k): int(v) for k, v in zip(unique.tolist(), freq.tolist())}

    rows: List[Dict[str, object]] = []
    for label in label_table.labels:
        key = int(label.key)
        name = (getattr(label, "label", "") or "").strip()

        if key == 0 and name.lower() in BACKGROUND_LABELS:
            continue

        if not name:
            name = f"label_{key}"

        row: Dict[str, object] = {"name": name, "label_key": key}

        rgba = [label.red, label.green, label.blue, label.alpha]
        if any(component is not None for component in rgba):
            row["color_rgba"] = [
                float(component) if component is not None else None
                for component in rgba
            ]

        if key in counts:
            row["vertex_count"] = counts[key]

        rows.append(row)

    if not rows:
        raise ValueError(f"GIFTI label file {path} does not contain usable labels")

    df = pd.DataFrame(rows)
    df["source_file"] = path.name

    if "hemi-L" in path.name:
        df["hemisphere"] = "left"
    elif "hemi-R" in path.name:
        df["hemisphere"] = "right"

    return df


def _read_cifti_label_table(path: Path) -> pd.DataFrame:
    """Extract label metadata from a CIFTI-2 dlabel file."""

    img = nib.load(str(path))
    axes = [img.header.get_axis(i) for i in range(img.ndim)]
    label_axes = [axis for axis in axes if isinstance(axis, LabelAxis)]

    if not label_axes:
        raise ValueError(f"CIFTI label file {path} does not expose a label axis")

    try:
        data = img.get_fdata(dtype=np.int32)
    except Exception:  # pragma: no cover - nibabel read failures
        data = None

    rows: List[Dict[str, object]] = []

    for axis in label_axes:
        for index, map_name in enumerate(axis.name.tolist()):
            label_dict = axis.label[index]
            counts: Dict[int, int] = {}

            if data is not None:
                if data.ndim == 1:
                    values = np.asarray(data, dtype=np.int32).ravel()
                elif index < data.shape[0]:
                    values = np.asarray(data[index], dtype=np.int32).ravel()
                else:
                    values = None

                if values is not None:
                    unique, freq = np.unique(values, return_counts=True)
                    counts = {
                        int(k): int(v) for k, v in zip(unique.tolist(), freq.tolist())
                    }

            for key, payload in label_dict.items():
                key_int = int(key)

                label_name = ""
                rgba = None

                if isinstance(payload, (tuple, list)):
                    label_name = (payload[0] or "").strip()
                    if len(payload) > 1:
                        rgba = payload[1]
                else:
                    label_name = str(payload)

                if key_int == 0 and label_name.lower() in BACKGROUND_LABELS:
                    continue

                if not label_name:
                    label_name = map_name or f"label_{key_int}"

                row: Dict[str, object] = {
                    "name": label_name,
                    "label_key": key_int,
                    "map_name": map_name,
                }

                if rgba and any(rgba):
                    row["color_rgba"] = [
                        float(component) if component is not None else None
                        for component in rgba
                    ]

                if key_int in counts:
                    row["vertex_count"] = counts[key_int]

                rows.append(row)

    if not rows:
        raise ValueError(f"CIFTI label file {path} does not contain usable labels")

    df = pd.DataFrame(rows).drop_duplicates(
        subset=["map_name", "label_key", "name"], keep="first"
    )
    df["source_file"] = path.name
    return df


def read_table(path: Path) -> pd.DataFrame:
    """Load an atlas definition into a pandas DataFrame."""
    suffixes = "".join(path.suffixes).lower()
    suffix = path.suffix.lower()

    if any(suffixes.endswith(label) for label in LABEL_FILE_SUFFIXES):
        if suffixes.endswith(".label.gii"):
            df = _read_gifti_label_table(path)
        else:
            df = _read_cifti_label_table(path)
    elif suffix in {".tsv", ".txt"}:
        df = pd.read_csv(path, sep="\t")
    elif suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix == ".json":
        data = pd.read_json(path)
        df = pd.DataFrame(data)
    else:
        raise ValueError(f"Unsupported file extension for atlas file: {path}")

    if df.empty:
        raise ValueError(f"Atlas file {path} did not contain any rows.")

    df.columns = [col.strip() for col in df.columns]
    if "source_file" not in df.columns:
        df["source_file"] = path.name

    return df


def discover_atlas_files(
    base_path: Path,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> List[AtlasFile]:
    """Locate atlas definition files under the base directory."""
    if not base_path.exists():
        raise FileNotFoundError(
            f"Neuromaps base path {base_path} not found. "
            "Download the dataset locally before running this script."
        )

    include_set = {slugify(item) for item in include} if include else None
    exclude_set = {slugify(item) for item in exclude} if exclude else set()

    atlas_files: List[AtlasFile] = []

    for path in base_path.rglob("*"):
        if not path.is_file():
            continue

        suffixes = "".join(path.suffixes).lower()
        suffix = path.suffix.lower()

        is_tabular = suffix in TABLE_SUFFIXES
        is_label_image = any(suffixes.endswith(label) for label in LABEL_FILE_SUFFIXES)

        if not (is_tabular or is_label_image):
            continue

        if is_tabular and path.name == "manifest.json":
            logger.debug("Skipping manifest file at %s", path)
            continue

        atlas_name = slugify(path.stem)
        if include_set and atlas_name not in include_set:
            continue

        if atlas_name in exclude_set:
            logger.debug("Skipping atlas %s due to exclude filter", atlas_name)
            continue

        atlas_files.append(AtlasFile(path=path, atlas=atlas_name))

    atlas_files.sort(key=lambda entry: entry.atlas)
    return atlas_files


# --------------------------------------------------------------------------- #
# Loading logic
# --------------------------------------------------------------------------- #


def build_node_properties(
    atlas: str,
    row: pd.Series,
    name_col: str,
    label_col: Optional[str],
    hemi_col: Optional[str],
    network_col: Optional[str],
    parent_col: Optional[str],
    coord_cols: Tuple[Optional[str], Optional[str], Optional[str]],
    extra_columns: List[str],
) -> Tuple[Dict[str, object], Optional[str]]:
    """Construct BrainRegion node properties and optional parent name."""
    raw_name = _string_or_none(row[name_col])
    if not raw_name:
        raise ValueError("Encountered row without a region name; cannot create node.")

    label_value = None
    if label_col:
        label_value = _string_or_none(row[label_col])

    atlas_slug = atlas.lower()
    region_slug = slugify(raw_name if label_value is None else label_value)
    node_id = f"{atlas_slug}:{region_slug}"

    properties: Dict[str, object] = {
        "id": node_id,
        "name": raw_name,
        "atlas": atlas_slug,
        "source": "neuromaps",
    }

    if label_value and label_value != raw_name:
        properties["label"] = label_value

    if hemi_col:
        hemi_value = _string_or_none(row[hemi_col], lowercase=True)
        if hemi_value:
            properties["hemisphere"] = hemi_value

    if network_col:
        network_value = _string_or_none(row[network_col])
        if network_value:
            properties["network"] = network_value

    x_col, y_col, z_col = coord_cols
    try:
        if x_col and y_col and z_col:
            x_val = float(row[x_col])
            y_val = float(row[y_col])
            z_val = float(row[z_col])
            properties["x"] = x_val
            properties["y"] = y_val
            properties["z"] = z_val
    except (TypeError, ValueError):
        # Ignore malformed coordinates but warn for visibility
        logger.debug(
            "Invalid coordinate triple for node %s in atlas %s", node_id, atlas
        )

    # Capture any remaining columns as metadata for later reference
    metadata = {}
    for column in extra_columns:
        value = row[column]
        if pd.isna(value):
            continue
        metadata[column] = value

    if metadata:
        properties["metadata_json"] = json.dumps(metadata, default=str)

    parent_value = None
    if parent_col:
        parent_value = _string_or_none(row[parent_col])

    return properties, parent_value


def insert_brain_regions(
    db: NeuromapsGraphDBProtocol,
    atlas_file: AtlasFile,
    df: pd.DataFrame,
    dry_run: bool = False,
) -> Tuple[int, int, Dict[str, str], Dict[str, Optional[str]]]:
    """
    Insert BrainRegion nodes for a given atlas.

    Returns:
        Tuple of (created_nodes, skipped_nodes, id_map, column_metadata)
    """
    lower_columns = {col.lower(): col for col in df.columns}

    name_col = detect_column(
        lower_columns.values(),
        ["name", "region", "parcel", "label", "node", "structure"],
    )
    if not name_col:
        raise ValueError(
            f"Atlas {atlas_file.atlas} missing an identifiable name column."
        )

    label_col = detect_column(
        lower_columns.values(), ["label", "longname", "fullname", "region_label"]
    )
    hemi_col = detect_column(
        lower_columns.values(), ["hemi", "hemisphere", "side", "network_hemi"]
    )
    network_col = detect_column(
        lower_columns.values(),
        ["network", "system", "community", "rsn", "macronetwork"],
    )
    parent_col = detect_column(
        lower_columns.values(),
        ["parent", "superregion", "lobe", "macroregion", "network_parent"],
    )

    x_col = detect_column(lower_columns.values(), ["x", "x_mni", "mni_x", "centroid_x"])
    y_col = detect_column(lower_columns.values(), ["y", "y_mni", "mni_y", "centroid_y"])
    z_col = detect_column(lower_columns.values(), ["z", "z_mni", "mni_z", "centroid_z"])

    reserved_cols = {
        col
        for col in [
            name_col,
            label_col,
            hemi_col,
            network_col,
            parent_col,
            x_col,
            y_col,
            z_col,
        ]
        if col is not None
    }
    extra_columns = [col for col in df.columns if col not in reserved_cols]

    created = 0
    skipped = 0
    node_id_map: Dict[str, str] = {}

    for _, row in df.iterrows():
        try:
            properties, parent_value = build_node_properties(
                atlas=atlas_file.atlas,
                row=row,
                name_col=name_col,
                label_col=label_col,
                hemi_col=hemi_col,
                network_col=network_col,
                parent_col=parent_col,
                coord_cols=(x_col, y_col, z_col),
                extra_columns=extra_columns,
            )
        except ValueError as exc:
            logger.warning("Skipping row due to error: %s", exc)
            skipped += 1
            continue

        node_id = properties["id"]
        name_key = properties["name"]
        node_id_map[name_key.lower()] = node_id
        node_id_map[slugify(name_key)] = node_id

        if label_col:
            label_key = _string_or_none(row[label_col])
            if label_key:
                node_id_map[label_key.lower()] = node_id
                node_id_map[slugify(label_key)] = node_id

        if parent_value:
            node_id_map.setdefault(parent_value.lower(), None)
            node_id_map.setdefault(slugify(parent_value), None)

        existing = db.find_nodes(labels="BrainRegion", properties={"id": node_id})
        if existing:
            skipped += 1
            continue

        if dry_run:
            created += 1
            continue

        db.create_node("BrainRegion", properties)
        created += 1

    logger.info(
        "Atlas %s processed: %d nodes created, %d skipped",
        atlas_file.atlas,
        created,
        skipped,
    )

    column_info = {
        "name_col": name_col,
        "parent_col": parent_col,
    }

    return created, skipped, node_id_map, column_info


def insert_part_of_relationships(
    db: NeuromapsGraphDBProtocol,
    atlas_file: AtlasFile,
    df: pd.DataFrame,
    node_id_lookup: Dict[str, str],
    parent_col: Optional[str],
    name_col: str,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Create PART_OF relationships according to parent assignments."""
    if not parent_col:
        return 0, 0

    created = 0
    skipped = 0

    for _, row in df.iterrows():
        child_name = _string_or_none(row[name_col])
        parent_name = _string_or_none(row[parent_col])
        if not child_name or not parent_name:
            continue

        child_lower = child_name.lower()
        parent_lower = parent_name.lower()

        child_id = node_id_lookup.get(child_lower)
        if not child_id:
            child_id = node_id_lookup.get(slugify(child_name))

        parent_id = node_id_lookup.get(parent_lower)
        if not parent_id:
            parent_id = node_id_lookup.get(slugify(parent_name))

        if not child_id or not parent_id:
            logger.debug(
                "PART_OF relationship skipped for atlas %s: "
                "child=%s parent=%s (missing nodes)",
                atlas_file.atlas,
                child_name,
                parent_name,
            )
            skipped += 1
            continue

        if dry_run:
            created += 1
            continue

        existing = db.find_relationships(
            start_node=child_id, end_node=parent_id, rel_type="PART_OF"
        )
        if existing:
            skipped += 1
            continue

        db.create_relationship(
            child_id,
            parent_id,
            "PART_OF",
            {
                "source": "neuromaps",
                "atlas": atlas_file.atlas.lower(),
            },
        )
        created += 1

    logger.info(
        "Atlas %s PART_OF relationships: %d created, %d skipped",
        atlas_file.atlas,
        created,
        skipped,
    )
    return created, skipped


__all__ = [
    "AtlasFile",
    "NeuromapsGraphDBProtocol",
    "build_node_properties",
    "detect_column",
    "discover_atlas_files",
    "insert_brain_regions",
    "insert_part_of_relationships",
    "read_table",
    "slugify",
]
