"""Compatibility module for label embedding helpers."""

from __future__ import annotations

import sys

from brain_researcher.core.ingestion.utils import label_embedder as _label_embedder

sys.modules[__name__] = _label_embedder
