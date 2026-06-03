"""
Database migration framework for BR-KG.
Implements KG-004: Database Migration Framework
"""

from .migration_framework import (
    Migration,
    MigrationManager,
    MigrationRecord,
    MigrationRunner,
)

__all__ = ["Migration", "MigrationRunner", "MigrationManager", "MigrationRecord"]
