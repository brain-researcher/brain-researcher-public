"""
Migration: Add performance indexes
Version: 003_add_performance_indexes
Created: 2025-08-18
"""

import sqlite3

from brain_researcher.services.br_kg.migrations import Migration


class Migration_003(Migration):
    """
    Add performance indexes for frequently queried columns.
    """

    def __init__(self):
        super().__init__(
            version="003_add_performance_indexes",
            description="Add performance indexes for common queries",
        )

    def up(self, db):
        """
        Create performance indexes.
        """
        if isinstance(db, sqlite3.Connection):
            conn = db
        else:
            conn = sqlite3.connect(db.db_path)

        try:
            # Composite indexes for common query patterns
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_nodes_type_created
                ON nodes(node_type, created_at DESC)
            """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_relationships_composite
                ON relationships(source_id, target_id, rel_type)
            """
            )

            # Full-text search preparation (SQLite FTS5)
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    id UNINDEXED,
                    node_type UNINDEXED,
                    content,
                    tokenize='porter unicode61'
                )
            """
            )

            # Populate FTS table from existing nodes
            conn.execute(
                """
                INSERT OR IGNORE INTO nodes_fts (id, node_type, content)
                SELECT id, node_type, properties FROM nodes
            """
            )

            # Create trigger to keep FTS in sync
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS nodes_fts_insert
                AFTER INSERT ON nodes
                BEGIN
                    INSERT INTO nodes_fts (id, node_type, content)
                    VALUES (new.id, new.node_type, new.properties);
                END
            """
            )

            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS nodes_fts_update
                AFTER UPDATE ON nodes
                BEGIN
                    UPDATE nodes_fts
                    SET content = new.properties
                    WHERE id = new.id;
                END
            """
            )

            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS nodes_fts_delete
                AFTER DELETE ON nodes
                BEGIN
                    DELETE FROM nodes_fts WHERE id = old.id;
                END
            """
            )

            conn.commit()
            print("✓ Created performance indexes and FTS")

        finally:
            if not isinstance(db, sqlite3.Connection):
                conn.close()

    def down(self, db):
        """
        Drop performance indexes.
        """
        if isinstance(db, sqlite3.Connection):
            conn = db
        else:
            conn = sqlite3.connect(db.db_path)

        try:
            # Drop triggers
            conn.execute("DROP TRIGGER IF EXISTS nodes_fts_delete")
            conn.execute("DROP TRIGGER IF EXISTS nodes_fts_update")
            conn.execute("DROP TRIGGER IF EXISTS nodes_fts_insert")

            # Drop FTS table
            conn.execute("DROP TABLE IF EXISTS nodes_fts")

            # Drop composite indexes
            conn.execute("DROP INDEX IF EXISTS idx_relationships_composite")
            conn.execute("DROP INDEX IF EXISTS idx_nodes_type_created")

            conn.commit()
            print("✓ Dropped performance indexes and FTS")

        finally:
            if not isinstance(db, sqlite3.Connection):
                conn.close()
