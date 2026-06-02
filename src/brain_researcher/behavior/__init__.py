"""Behavior task generation package (psyflow-oriented).

Public surface
--------------
- ``task_spec``: Pydantic v2 contracts for behavior task specs, reviews, and
  psyflow bundles, plus a deterministic ``spec_digest`` helper.
- ``catalog``: paradigm defaults and BR → psyflow config mappers.
- ``psyflow_adapter``: lazy psyflow integration (scaffold writer, validator,
  run ingest).
- ``workflow``: end-to-end glue (plan → resolve → review → generate →
  optional validate → optional ingest).

Nothing in this package imports ``psyflow`` at module import time; heavy
integration is gated through ``psyflow_adapter._import_psyflow``.
"""

from __future__ import annotations

__all__: list[str] = []
