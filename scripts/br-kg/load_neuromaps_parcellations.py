#!/usr/bin/env python3
"""CLI wrapper for loading Neuromaps parcellations into BR-KG."""

from brain_researcher.services.br_kg.spatial.neuromaps_parcellations import (
    AtlasFile,
    build_node_properties,
    detect_column,
    discover_atlas_files,
    insert_brain_regions,
    insert_part_of_relationships,
    main,
    parse_args,
    read_table,
    slugify,
)

__all__ = [
    "AtlasFile",
    "build_node_properties",
    "detect_column",
    "discover_atlas_files",
    "insert_brain_regions",
    "insert_part_of_relationships",
    "main",
    "parse_args",
    "read_table",
    "slugify",
]


if __name__ == "__main__":
    main()
