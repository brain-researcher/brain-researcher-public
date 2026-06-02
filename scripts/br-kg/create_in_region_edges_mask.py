#!/usr/bin/env python3
"""CLI wrapper for mask-based Coordinate -> BrainRegion mapping."""

from brain_researcher.services.br_kg.spatial.create_in_region_edges_mask import (
    fetch_atlas,
    main,
    voxel_label,
)

__all__ = ["fetch_atlas", "main", "voxel_label"]


if __name__ == "__main__":
    main()
