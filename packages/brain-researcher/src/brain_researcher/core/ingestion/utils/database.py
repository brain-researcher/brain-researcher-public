"""Minimal database helpers for ingestion validation storage."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def store_validation_result(db_path: str, record: Dict[str, Any]) -> None:
    """Persist a validation record.

    This lightweight implementation appends JSON lines to the target path,
    which keeps the function available for tests and local usage without
    requiring a database dependency.
    """
    try:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.warning("Failed to store validation result: %s", exc)
