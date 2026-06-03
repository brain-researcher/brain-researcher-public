"""
Database migration framework for BR-KG.
Implements KG-004: Database Migration Framework
"""

from .migration_framework import (
    Migration,
    MigrationRunner,
    MigrationManager,
    MigrationRecord
)

__all__ = ['Migration', 'MigrationRunner', 'MigrationManager', 'MigrationRecord']