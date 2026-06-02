#!/usr/bin/env python3
"""CLI wrapper for ACTIVATES edge creation."""

from brain_researcher.services.br_kg.spatial.create_activation_edges import (
    DEFAULT_ACTIVATION_LABELS,
    PUBLICATION_NODE_LABELS,
    build_parser,
    collect_coordinate_evidence,
    create_activation_edges,
    main,
    run_activation_edge_creation,
    validate_database_structure,
)

__all__ = [
    "DEFAULT_ACTIVATION_LABELS",
    "PUBLICATION_NODE_LABELS",
    "build_parser",
    "collect_coordinate_evidence",
    "create_activation_edges",
    "main",
    "run_activation_edge_creation",
    "validate_database_structure",
]


if __name__ == "__main__":
    raise SystemExit(main())
