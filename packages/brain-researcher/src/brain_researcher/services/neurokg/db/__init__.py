"""Canonical runtime helpers for BR-KG database bootstrap and schema setup."""

from .bootstrap import get_db, seed
from .schema import setup_schema

__all__ = ["get_db", "seed", "setup_schema"]
