"""
Database migration framework for BR-KG.
Implements KG-004: Version-controlled schema migrations with rollback capability.
"""

import os
import json
import sqlite3
import hashlib
import importlib.util
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import logging
from abc import ABC, abstractmethod
import traceback

logger = logging.getLogger(__name__)


@dataclass
class MigrationRecord:
    """Record of an applied migration."""
    version: str
    name: str
    checksum: str
    applied_at: str
    execution_time: float
    status: str  # 'pending', 'applied', 'failed', 'rolled_back'
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)


class Migration(ABC):
    """
    Base class for database migrations.
    
    Each migration must implement up() and down() methods.
    """
    
    def __init__(self, version: str, description: str = ""):
        """
        Initialize migration.
        
        Args:
            version: Version string (e.g., "001", "002_add_users")
            description: Human-readable description
        """
        self.version = version
        self.description = description
        self.hooks = {
            'before_up': [],
            'after_up': [],
            'before_down': [],
            'after_down': []
        }
    
    @abstractmethod
    def up(self, db):
        """
        Apply the migration (forward).
        
        Args:
            db: Database connection or graph database instance
        """
        pass
    
    @abstractmethod
    def down(self, db):
        """
        Rollback the migration (backward).
        
        Args:
            db: Database connection or graph database instance
        """
        pass
    
    def add_hook(self, hook_type: str, callback: Callable):
        """
        Add a pre/post hook.
        
        Args:
            hook_type: One of 'before_up', 'after_up', 'before_down', 'after_down'
            callback: Function to call
        """
        if hook_type in self.hooks:
            self.hooks[hook_type].append(callback)
    
    def run_hooks(self, hook_type: str, db):
        """Run all hooks of a given type."""
        for hook in self.hooks.get(hook_type, []):
            try:
                hook(db)
            except Exception as e:
                logger.warning(f"Hook {hook_type} failed: {e}")
    
    def get_checksum(self) -> str:
        """Calculate checksum of migration code."""
        # Get source code of up and down methods
        import inspect
        up_source = inspect.getsource(self.up)
        down_source = inspect.getsource(self.down)
        combined = f"{up_source}{down_source}"
        
        return hashlib.sha256(combined.encode()).hexdigest()[:16]


class MigrationRunner:
    """
    Executes migrations and manages migration state.
    """
    
    def __init__(self, db_path: str = "neurokg_graph.db"):
        """
        Initialize migration runner.
        
        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self._init_migration_table()
    
    def _init_migration_table(self):
        """Create migration history table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    version TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    execution_time REAL NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT
                )
            """)
            
            # Add index for faster queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_migrations_status 
                ON _migrations(status)
            """)
            
            conn.commit()
    
    def get_db_connection(self):
        """
        Get database connection.
        
        Returns appropriate database instance based on type.
        For migrations, we always return a raw SQLite connection
        to avoid circular dependencies with the graph database.
        """
        # Always return raw SQLite connection for migrations
        # This avoids issues with the graph database expecting
        # tables that may not exist yet
        return sqlite3.connect(self.db_path)
    
    def get_applied_migrations(self) -> List[MigrationRecord]:
        """Get list of applied migrations."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT version, name, checksum, applied_at, 
                       execution_time, status, error_message
                FROM _migrations
                WHERE status = 'applied'
                ORDER BY version
            """)
            
            migrations = []
            for row in cursor.fetchall():
                migrations.append(MigrationRecord(
                    version=row[0],
                    name=row[1],
                    checksum=row[2],
                    applied_at=row[3],
                    execution_time=row[4],
                    status=row[5],
                    error_message=row[6]
                ))
            
            return migrations
    
    def is_applied(self, version: str) -> bool:
        """Check if a migration has been applied."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM _migrations WHERE version = ? AND status = 'applied'",
                (version,)
            )
            return cursor.fetchone() is not None
    
    def apply_migration(self, migration: Migration) -> bool:
        """
        Apply a single migration.
        
        Args:
            migration: Migration to apply
        
        Returns:
            True if successful, False otherwise
        """
        if self.is_applied(migration.version):
            logger.info(f"Migration {migration.version} already applied")
            return True
        
        logger.info(f"Applying migration {migration.version}: {migration.description}")
        
        start_time = datetime.now()
        db = self.get_db_connection()
        
        try:
            # Run pre-hook
            migration.run_hooks('before_up', db)
            
            # Apply migration
            migration.up(db)
            
            # Run post-hook
            migration.run_hooks('after_up', db)
            
            # Record success
            execution_time = (datetime.now() - start_time).total_seconds()
            self._record_migration(
                migration=migration,
                status='applied',
                execution_time=execution_time
            )
            
            # Close database connection
            if hasattr(db, 'close'):
                db.close()
            
            logger.info(f"Migration {migration.version} applied successfully in {execution_time:.2f}s")
            return True
            
        except Exception as e:
            logger.error(f"Migration {migration.version} failed: {e}")
            
            # Record failure
            execution_time = (datetime.now() - start_time).total_seconds()
            self._record_migration(
                migration=migration,
                status='failed',
                execution_time=execution_time,
                error_message=str(e)
            )
            
            # Try to close database connection
            if hasattr(db, 'close'):
                db.close()
            
            return False
    
    def rollback_migration(self, migration: Migration) -> bool:
        """
        Rollback a single migration.
        
        Args:
            migration: Migration to rollback
        
        Returns:
            True if successful, False otherwise
        """
        if not self.is_applied(migration.version):
            logger.info(f"Migration {migration.version} not applied, skipping rollback")
            return True
        
        logger.info(f"Rolling back migration {migration.version}: {migration.description}")
        
        start_time = datetime.now()
        db = self.get_db_connection()
        
        try:
            # Run pre-hook
            migration.run_hooks('before_down', db)
            
            # Rollback migration
            migration.down(db)
            
            # Run post-hook
            migration.run_hooks('after_down', db)
            
            # Update status
            execution_time = (datetime.now() - start_time).total_seconds()
            self._update_migration_status(
                version=migration.version,
                status='rolled_back',
                execution_time=execution_time
            )
            
            # Close database connection
            if hasattr(db, 'close'):
                db.close()
            
            logger.info(f"Migration {migration.version} rolled back successfully in {execution_time:.2f}s")
            return True
            
        except Exception as e:
            logger.error(f"Rollback of migration {migration.version} failed: {e}")
            
            # Record failure
            self._update_migration_status(
                version=migration.version,
                status='rollback_failed',
                error_message=str(e)
            )
            
            # Try to close database connection
            if hasattr(db, 'close'):
                db.close()
            
            return False
    
    def _record_migration(
        self,
        migration: Migration,
        status: str,
        execution_time: float,
        error_message: Optional[str] = None
    ):
        """Record migration in history table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO _migrations 
                (version, name, checksum, applied_at, execution_time, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                migration.version,
                migration.description,
                migration.get_checksum(),
                datetime.now().isoformat(),
                execution_time,
                status,
                error_message
            ))
            conn.commit()
    
    def _update_migration_status(
        self,
        version: str,
        status: str,
        execution_time: Optional[float] = None,
        error_message: Optional[str] = None
    ):
        """Update migration status in history table."""
        with sqlite3.connect(self.db_path) as conn:
            if execution_time is not None:
                conn.execute("""
                    UPDATE _migrations 
                    SET status = ?, execution_time = ?, error_message = ?
                    WHERE version = ?
                """, (status, execution_time, error_message, version))
            else:
                conn.execute("""
                    UPDATE _migrations 
                    SET status = ?, error_message = ?
                    WHERE version = ?
                """, (status, error_message, version))
            conn.commit()
    
    def verify_checksums(self, migrations: List[Migration]) -> List[Tuple[str, bool]]:
        """
        Verify that applied migrations haven't changed.
        
        Returns:
            List of (version, is_valid) tuples
        """
        results = []
        applied = {m.version: m.checksum for m in self.get_applied_migrations()}
        
        for migration in migrations:
            if migration.version in applied:
                current_checksum = migration.get_checksum()
                is_valid = current_checksum == applied[migration.version]
                results.append((migration.version, is_valid))
                
                if not is_valid:
                    logger.warning(
                        f"Migration {migration.version} has changed since it was applied! "
                        f"Expected: {applied[migration.version]}, Got: {current_checksum}"
                    )
        
        return results


class MigrationManager:
    """
    High-level migration management.
    """
    
    def __init__(
        self,
        migrations_dir: str = "migrations",
        db_path: str = "neurokg_graph.db"
    ):
        """
        Initialize migration manager.
        
        Args:
            migrations_dir: Directory containing migration files
            db_path: Path to database
        """
        self.migrations_dir = Path(migrations_dir)
        self.runner = MigrationRunner(db_path)
        self.migrations = self._load_migrations()
    
    def _load_migrations(self) -> List[Migration]:
        """Load all migrations from directory."""
        migrations = []
        
        if not self.migrations_dir.exists():
            logger.warning(f"Migrations directory {self.migrations_dir} does not exist")
            return migrations
        
        # Load Python migration files
        for file_path in sorted(self.migrations_dir.glob("*.py")):
            if file_path.name.startswith("_"):
                continue  # Skip private files
            
            try:
                # Load module dynamically
                spec = importlib.util.spec_from_file_location(
                    file_path.stem,
                    file_path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Find Migration subclass
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, Migration) and 
                        attr != Migration):
                        # Instantiate migration
                        migration = attr()
                        migrations.append(migration)
                        logger.debug(f"Loaded migration: {migration.version}")
                        break
                        
            except Exception as e:
                logger.error(f"Failed to load migration from {file_path}: {e}")
        
        # Sort by version
        migrations.sort(key=lambda m: m.version)
        
        return migrations
    
    def create_migration(self, name: str) -> Path:
        """
        Create a new migration file from template.
        
        Args:
            name: Name for the migration
        
        Returns:
            Path to created migration file
        """
        # Generate version based on timestamp
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        version = f"{timestamp}_{name}"
        
        # Create migrations directory if needed
        self.migrations_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate file
        file_path = self.migrations_dir / f"{version}.py"
        
        template = f'''"""
Migration: {name}
Version: {version}
Created: {datetime.now().isoformat()}
"""

from brain_researcher.services.neurokg.migrations import Migration


class Migration_{timestamp}(Migration):
    """
    {name}
    """
    
    def __init__(self):
        super().__init__(
            version="{version}",
            description="{name}"
        )
    
    def up(self, db):
        """
        Apply migration.
        
        Args:
            db: Database instance (NeuroKGGraphDB or sqlite connection)
        """
        # TODO: Implement forward migration
        pass
    
    def down(self, db):
        """
        Rollback migration.
        
        Args:
            db: Database instance (NeuroKGGraphDB or sqlite connection)
        """
        # TODO: Implement backward migration
        pass
'''
        
        file_path.write_text(template)
        logger.info(f"Created migration: {file_path}")
        
        return file_path
    
    def migrate(self, target: Optional[str] = None) -> bool:
        """
        Run migrations up to target version.
        
        Args:
            target: Target version (None = latest)
        
        Returns:
            True if all migrations successful
        """
        # Verify checksums first
        checksum_results = self.runner.verify_checksums(self.migrations)
        invalid = [v for v, valid in checksum_results if not valid]
        
        if invalid:
            logger.error(f"Invalid checksums detected for migrations: {invalid}")
            logger.error("Migrations have been modified after being applied!")
            return False
        
        # Get migrations to apply
        applied = {m.version for m in self.runner.get_applied_migrations()}
        
        success = True
        for migration in self.migrations:
            # Stop at target version
            if target and migration.version > target:
                break
            
            # Skip if already applied
            if migration.version in applied:
                continue
            
            # Apply migration
            if not self.runner.apply_migration(migration):
                success = False
                break
        
        return success
    
    def rollback(self, steps: int = 1) -> bool:
        """
        Rollback last N migrations.
        
        Args:
            steps: Number of migrations to rollback
        
        Returns:
            True if all rollbacks successful
        """
        applied = self.runner.get_applied_migrations()
        applied.reverse()  # Start with most recent
        
        # Get migrations to rollback
        to_rollback = applied[:steps]
        
        # Find corresponding Migration objects
        migration_map = {m.version: m for m in self.migrations}
        
        success = True
        for record in to_rollback:
            if record.version in migration_map:
                migration = migration_map[record.version]
                if not self.runner.rollback_migration(migration):
                    success = False
                    break
            else:
                logger.error(f"Migration {record.version} not found in migrations directory")
                success = False
                break
        
        return success
    
    def status(self) -> Dict[str, Any]:
        """
        Get migration status.
        
        Returns:
            Status information
        """
        applied = self.runner.get_applied_migrations()
        applied_versions = {m.version for m in applied}
        
        pending = [m for m in self.migrations if m.version not in applied_versions]
        
        return {
            "database": self.runner.db_path,
            "applied": len(applied),
            "pending": len(pending),
            "total": len(self.migrations),
            "applied_migrations": [m.to_dict() for m in applied],
            "pending_migrations": [
                {"version": m.version, "description": m.description}
                for m in pending
            ]
        }
    
    def reset(self) -> bool:
        """
        Rollback all migrations (dangerous!).
        
        Returns:
            True if successful
        """
        logger.warning("Resetting all migrations - this will destroy data!")
        
        applied = self.runner.get_applied_migrations()
        return self.rollback(len(applied))