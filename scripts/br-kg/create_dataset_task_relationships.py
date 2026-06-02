#!/usr/bin/env python3
"""CLI wrapper for Dataset->Task relationship creation."""

from brain_researcher.services.br_kg.etl.dataset_task_relationships import (
    DEFAULT_CATALOGS,
    DEFAULT_TASK_MAPPING,
    DEFAULT_TASK_SYNONYMS,
    DEFAULT_TAXONOMY_ALIASES,
    METHOD_CONF,
    SOURCE_CONF,
    EdgeRecord,
    _build_edge_props,
    _chunked,
    _group_edges,
    _infer_bids_source,
    _infer_dataset_task_source,
    _infer_source_key,
    _is_path_under_any_prefix,
    _iter_bids_task_labels,
    _iter_dataset_task_props,
    _iter_fmri_datasets_missing_task_edges,
    _iter_task_rows,
    _load_dataset_ids,
    _load_task_index,
    _method_to_prov_method,
    _parse_rel_types,
    _write_edges,
    main,
)

__all__ = [
    "DEFAULT_CATALOGS",
    "DEFAULT_TASK_MAPPING",
    "DEFAULT_TASK_SYNONYMS",
    "DEFAULT_TAXONOMY_ALIASES",
    "EdgeRecord",
    "METHOD_CONF",
    "SOURCE_CONF",
    "_build_edge_props",
    "_chunked",
    "_group_edges",
    "_infer_bids_source",
    "_infer_dataset_task_source",
    "_infer_source_key",
    "_is_path_under_any_prefix",
    "_iter_bids_task_labels",
    "_iter_dataset_task_props",
    "_iter_fmri_datasets_missing_task_edges",
    "_iter_task_rows",
    "_load_dataset_ids",
    "_load_task_index",
    "_method_to_prov_method",
    "_parse_rel_types",
    "_write_edges",
    "main",
]


if __name__ == "__main__":
    main()
