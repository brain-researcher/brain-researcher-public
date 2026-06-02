#!/usr/bin/env python3
"""CLI wrapper for Coordinate -> BrainRegion spatial mapping."""

from brain_researcher.services.br_kg.spatial.create_in_region_edges import (
    ATLAS_NIFTI_PATHS,
    CoordinateRegionMapper,
    load_atlas_nifti,
    main,
    mni_to_label,
)

__all__ = [
    "ATLAS_NIFTI_PATHS",
    "CoordinateRegionMapper",
    "load_atlas_nifti",
    "main",
    "mni_to_label",
]


if __name__ == "__main__":
    main()
