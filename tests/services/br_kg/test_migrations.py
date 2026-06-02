"""
Tests for BR-KG database migration framework.
"""

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from brain_researcher.services.br_kg.migrations import (
    Migration,
    MigrationManager,
    MigrationRecord,
    MigrationRunner,
)


class TestMigration(Migration):
    """Test migration for testing purposes."""

    def __init__(self, version="test_001", should_fail=False):
        super().__init__(version=version, description="Test migration")
        self.should_fail = should_fail
        self.up_called = False
        self.down_called = False

    def up(self, db):
        """Apply test migration."""
        self.up_called = True
        if self.should_fail:
            raise Exception("Test failure")

        # Create a test table
        if isinstance(db, sqlite3.Connection):
            conn = db
        else:
            conn = sqlite3.connect(db.db_path)

        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_table (
                    id INTEGER PRIMARY KEY,
                    value TEXT
                )
            """
            )
            conn.commit()
        finally:
            if not isinstance(db, sqlite3.Connection):
                conn.close()

    def down(self, db):
        """Rollback test migration."""
        self.down_called = True
        if self.should_fail:
            raise Exception("Test rollback failure")

        # Drop test table
        if isinstance(db, sqlite3.Connection):
            conn = db
        else:
            conn = sqlite3.connect(db.db_path)

        try:
            conn.execute("DROP TABLE IF EXISTS test_table")
            conn.commit()
        finally:
            if not isinstance(db, sqlite3.Connection):
                conn.close()


class TestMigrationRunner:
    """Test MigrationRunner functionality."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        yield db_path

        # Cleanup
        try:
            os.unlink(db_path)
        except:
            pass

    @pytest.fixture
    def runner(self, temp_db):
        """Create migration runner with temp database."""
        return MigrationRunner(db_path=temp_db)

    def test_init_migration_table(self, runner, temp_db):
        """Test migration table initialization."""
        # Check table exists
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='_migrations'
        """
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_apply_migration(self, runner, temp_db):
        """Test applying a migration."""
        migration = TestMigration(version="test_001")

        # Apply migration
        success = runner.apply_migration(migration)
        assert success
        assert migration.up_called

        # Check migration is recorded
        assert runner.is_applied("test_001")

        # Check test table was created
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='test_table'
        """
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_apply_migration_twice(self, runner):
        """Test applying same migration twice."""
        migration = TestMigration(version="test_001")

        # Apply first time
        assert runner.apply_migration(migration)

        # Apply second time - should skip
        migration.up_called = False
        assert runner.apply_migration(migration)
        assert not migration.up_called  # Should not call up() again

    def test_rollback_migration(self, runner, temp_db):
        """Test rolling back a migration."""
        migration = TestMigration(version="test_001")

        # Apply migration
        runner.apply_migration(migration)
        assert runner.is_applied("test_001")

        # Rollback
        success = runner.rollback_migration(migration)
        assert success
        assert migration.down_called

        # Check migration status updated
        applied = runner.get_applied_migrations()
        assert all(
            m.version != "test_001" or m.status == "rolled_back" for m in applied
        )

        # Check test table was dropped
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='test_table'
        """
        )
        assert cursor.fetchone() is None
        conn.close()

    def test_migration_failure(self, runner):
        """Test handling migration failure."""
        migration = TestMigration(version="fail_001", should_fail=True)

        # Apply should fail
        success = runner.apply_migration(migration)
        assert not success

        # Check failure is recorded
        conn = sqlite3.connect(runner.db_path)
        cursor = conn.execute(
            """
            SELECT status, error_message FROM _migrations
            WHERE version = 'fail_001'
        """
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "failed"
        assert "Test failure" in row[1]
        conn.close()

    def test_get_applied_migrations(self, runner):
        """Test getting list of applied migrations."""
        # Apply multiple migrations
        for i in range(3):
            migration = TestMigration(version=f"test_{i:03d}")
            runner.apply_migration(migration)

        # Get applied
        applied = runner.get_applied_migrations()
        assert len(applied) == 3
        assert all(isinstance(m, MigrationRecord) for m in applied)
        assert [m.version for m in applied] == ["test_000", "test_001", "test_002"]

    def test_verify_checksums(self, runner):
        """Test checksum verification."""
        migration1 = TestMigration(version="test_001")
        migration2 = TestMigration(version="test_002")

        # Apply migrations
        runner.apply_migration(migration1)
        runner.apply_migration(migration2)

        # Verify - should all be valid
        results = runner.verify_checksums([migration1, migration2])
        assert len(results) == 2
        assert all(valid for _, valid in results)

        # Modify migration by changing the up method (simulate code change)
        # This actually changes the source code checksum
        original_up = migration1.up

        def modified_up(db):
            """Modified up method with different source."""
            original_up(db)
            # Additional code that changes the checksum
            pass

        migration1.up = modified_up

        # Verify again - first should be invalid
        results = runner.verify_checksums([migration1, migration2])
        assert len(results) == 2
        assert not results[0][1]  # First is invalid
        assert results[1][1]  # Second is still valid


class TestMigrationManager:
    """Test MigrationManager functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for migrations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        yield db_path

        # Cleanup
        try:
            os.unlink(db_path)
        except:
            pass

    @pytest.fixture
    def manager(self, temp_dir, temp_db):
        """Create migration manager with temp paths."""
        return MigrationManager(migrations_dir=str(temp_dir), db_path=temp_db)

    def test_create_migration(self, manager, temp_dir):
        """Test creating a new migration file."""
        # Create migration
        file_path = manager.create_migration("test_feature")

        # Check file exists
        assert file_path.exists()
        assert file_path.parent == temp_dir
        assert "test_feature" in file_path.name

        # Check content
        content = file_path.read_text()
        assert "class Migration_" in content
        assert "def up(self, db):" in content
        assert "def down(self, db):" in content

    def test_load_migrations(self, manager, temp_dir):
        """Test loading migrations from directory."""
        # Create migration files
        for i in range(3):
            file_path = temp_dir / f"{i:03d}_test.py"
            file_path.write_text(
                f"""
from brain_researcher.services.br_kg.migrations import Migration

class Migration_{i:03d}(Migration):
    def __init__(self):
        super().__init__(version="{i:03d}_test", description="Test {i}")

    def up(self, db):
        pass

    def down(self, db):
        pass
"""
            )

        # Reload migrations
        manager.migrations = manager._load_migrations()

        # Check loaded
        assert len(manager.migrations) == 3
        assert [m.version for m in manager.migrations] == [
            "000_test",
            "001_test",
            "002_test",
        ]

    def test_migrate(self, manager, temp_dir):
        """Test running migrations."""
        # Create migration files
        for i in range(3):
            file_path = temp_dir / f"{i:03d}_test.py"
            file_path.write_text(
                f"""
from brain_researcher.services.br_kg.migrations import Migration
import sqlite3

class Migration_{i:03d}(Migration):
    def __init__(self):
        super().__init__(version="{i:03d}_test", description="Test {i}")

    def up(self, db):
        conn = sqlite3.connect(db.db_path) if hasattr(db, 'db_path') else db
        conn.execute("CREATE TABLE IF NOT EXISTS test_{i} (id INTEGER)")
        conn.commit()
        if hasattr(db, 'db_path'):
            conn.close()

    def down(self, db):
        conn = sqlite3.connect(db.db_path) if hasattr(db, 'db_path') else db
        conn.execute("DROP TABLE IF EXISTS test_{i}")
        conn.commit()
        if hasattr(db, 'db_path'):
            conn.close()
"""
            )

        # Reload and migrate
        manager.migrations = manager._load_migrations()
        success = manager.migrate()
        assert success

        # Check status
        status = manager.status()
        assert status["applied"] == 3
        assert status["pending"] == 0

    def test_migrate_to_target(self, manager, temp_dir):
        """Test migrating to specific version."""
        # Create migrations
        for i in range(5):
            file_path = temp_dir / f"{i:03d}_test.py"
            file_path.write_text(
                f"""
from brain_researcher.services.br_kg.migrations import Migration

class Migration_{i:03d}(Migration):
    def __init__(self):
        super().__init__(version="{i:03d}_test", description="Test {i}")

    def up(self, db):
        pass

    def down(self, db):
        pass
"""
            )

        # Reload and migrate to version 002
        manager.migrations = manager._load_migrations()
        success = manager.migrate(target="002_test")
        assert success

        # Check only first 3 applied
        status = manager.status()
        assert status["applied"] == 3
        assert status["pending"] == 2

    def test_rollback(self, manager, temp_dir, temp_db):
        """Test rolling back migrations."""
        # Create and apply migrations
        for i in range(3):
            file_path = temp_dir / f"{i:03d}_test.py"
            file_path.write_text(
                f"""
from brain_researcher.services.br_kg.migrations import Migration
import sqlite3

class Migration_{i:03d}(Migration):
    def __init__(self):
        super().__init__(version="{i:03d}_test", description="Test {i}")

    def up(self, db):
        conn = sqlite3.connect(db.db_path) if hasattr(db, 'db_path') else db
        conn.execute("CREATE TABLE IF NOT EXISTS test_{i} (id INTEGER)")
        conn.commit()
        if hasattr(db, 'db_path'):
            conn.close()

    def down(self, db):
        conn = sqlite3.connect(db.db_path) if hasattr(db, 'db_path') else db
        conn.execute("DROP TABLE IF EXISTS test_{i}")
        conn.commit()
        if hasattr(db, 'db_path'):
            conn.close()
"""
            )

        # Apply all
        manager.migrations = manager._load_migrations()
        manager.migrate()

        # Rollback 2
        success = manager.rollback(steps=2)
        assert success

        # Check status
        status = manager.status()
        # Note: rolled back migrations may still appear in applied list with different status

        # Check tables - only first table should exist
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name LIKE 'test_%'
            ORDER BY name
        """
        )
        tables = [row[0] for row in cursor.fetchall()]
        assert "test_0" in tables
        assert "test_1" not in tables
        assert "test_2" not in tables
        conn.close()

    def test_status(self, manager, temp_dir):
        """Test getting migration status."""
        # Create migrations
        for i in range(3):
            file_path = temp_dir / f"{i:03d}_test.py"
            file_path.write_text(
                f"""
from brain_researcher.services.br_kg.migrations import Migration

class Migration_{i:03d}(Migration):
    def __init__(self):
        super().__init__(version="{i:03d}_test", description="Test {i}")

    def up(self, db):
        pass

    def down(self, db):
        pass
"""
            )

        # Reload migrations
        manager.migrations = manager._load_migrations()

        # Get initial status
        status = manager.status()
        assert status["total"] == 3
        assert status["applied"] == 0
        assert status["pending"] == 3
        assert len(status["pending_migrations"]) == 3

        # Apply one migration
        manager.migrate(target="000_test")

        # Check updated status
        status = manager.status()
        assert status["applied"] == 1
        assert status["pending"] == 2


class TestRealMigrations:
    """Test the actual migration files we created."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        yield db_path

        # Cleanup
        try:
            os.unlink(db_path)
        except:
            pass

    def test_initial_schema_migration(self, temp_db):
        """Test the 001_initial_schema migration."""
        # Import the correct migration module
        import importlib.util
        import sys
        from pathlib import Path

        # Load the migration module directly
        migration_path = (
            Path(__file__).parent.parent.parent.parent
            / "brain_researcher/services/br_kg/migrations/migrations/001_initial_schema.py"
        )
        spec = importlib.util.spec_from_file_location("migration_001", migration_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        runner = MigrationRunner(db_path=temp_db)
        migration = module.Migration_001()

        # Apply migration
        success = runner.apply_migration(migration)
        assert success

        # Check tables created
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name
        """
        )
        tables = [row[0] for row in cursor.fetchall()]

        assert "_migrations" in tables
        assert "graph_metadata" in tables
        assert "nodes" in tables
        assert "relationships" in tables

        # Check indexes
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='index' AND name LIKE 'idx_%'
            ORDER BY name
        """
        )
        indexes = [row[0] for row in cursor.fetchall()]

        assert "idx_migrations_status" in indexes
        assert "idx_nodes_type" in indexes
        assert "idx_relationships_source" in indexes
        assert "idx_relationships_target" in indexes
        assert "idx_relationships_type" in indexes

        conn.close()

        # Test rollback
        success = runner.rollback_migration(migration)
        assert success

        # Check tables dropped
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('nodes', 'relationships', 'graph_metadata')
        """
        )
        assert cursor.fetchone() is None
        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
