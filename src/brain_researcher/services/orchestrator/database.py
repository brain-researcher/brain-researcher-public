"""Lightweight database dependency for survey endpoints (test-friendly).

This module intentionally uses an in-memory SQLite engine by default to avoid
external DB requirements during unit tests. Production deployments should
override the engine/SessionLocal via environment-specific wiring.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .survey_models import Base, create_survey_tables

# Default to in-memory SQLite; can be overridden by env var if needed.
DATABASE_URL = os.getenv("SURVEY_DATABASE_URL", "sqlite:///:memory:")

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create survey tables if not present."""
    create_survey_tables(engine)


@contextmanager
def get_db() -> Iterator:
    """FastAPI dependency yielding a DB session."""
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
