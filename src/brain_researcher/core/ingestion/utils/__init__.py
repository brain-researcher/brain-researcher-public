"""Ingestion utilities."""

from .ndjson_parser import iter_ndjson, open_any, parse_ndjson_file

__all__ = ["iter_ndjson", "open_any", "parse_ndjson_file"]