#!/usr/bin/env python3
"""CLI wrapper for concept-region strength calculation helpers."""

from brain_researcher.services.br_kg.scoring.calculate_strength import (
    _get_node_by_id,
    create_synthetic_coordinate_data,
    main,
    update_database_strengths,
)

__all__ = [
    "_get_node_by_id",
    "create_synthetic_coordinate_data",
    "main",
    "update_database_strengths",
]


if __name__ == "__main__":
    main()
